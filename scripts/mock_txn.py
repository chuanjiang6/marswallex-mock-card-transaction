#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MarsWallex 测试环境模拟卡交易工具。

自动生成 OpenAPI 认证头与签名，调用 POST /v1/card/mock-transactions，
并提供按交易单号查询的 query 命令。只允许访问测试环境域名。

签名规则（与服务端一致）：
    Authorization: Basic base64(developer_id:api_token)
    F-Signature:   t={epoch},v={base64(SHA256withRSA(签名原文))}
    签名原文:       METHOD&URI&EPOCH&BODY[&URL编码后的QUERY]
    URI 含 context-path，例如 /portal/api/v1/card/mock-transactions

依赖：Python 3.8+，pip install cryptography
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ALLOWED_HOST_SUFFIXES = ("feibeiglobal-test.com",)
MOCK_PATH = "/v1/card/mock-transactions"
QUERY_PATHS = {
    "authorization": "/v1/card/transactions/authorization",
    "settlement": "/v1/card/transactions/settlement",
}
DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "config.env")
CONFIG_KEYS = ("BASE_URL", "DEVELOPER_ID", "API_TOKEN", "PRIVATE_KEY_FILE", "PRIVATE_KEY", "TIMEOUT_SECONDS")

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_NETWORK = 4


class ConfigError(Exception):
    pass


def load_config(path):
    """读取 KEY=VALUE 配置文件，同名环境变量 MARSWALLEX_<KEY> 优先。"""
    conf = {"_CONFIG_DIR": os.path.dirname(os.path.abspath(path))}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                conf[key.strip()] = value.strip().strip('"').strip("'")
    for key in CONFIG_KEYS:
        env_value = os.environ.get("MARSWALLEX_" + key)
        if env_value:
            conf[key] = env_value
    for key in ("BASE_URL", "DEVELOPER_ID", "API_TOKEN"):
        if not conf.get(key) or conf[key].startswith("<"):
            raise ConfigError("配置项 %s 未填写，请编辑 %s 或设置环境变量 MARSWALLEX_%s" % (key, path, key))
    if not conf.get("PRIVATE_KEY_FILE") and not conf.get("PRIVATE_KEY"):
        raise ConfigError("PRIVATE_KEY_FILE 与 PRIVATE_KEY 至少填写一个")
    host = urllib.parse.urlparse(conf["BASE_URL"]).hostname or ""
    if not any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES):
        raise ConfigError("BASE_URL 的域名 %s 不是测试环境，本工具只允许访问 %s" % (host, ", ".join(ALLOWED_HOST_SUFFIXES)))
    return conf


def load_private_key(conf):
    """支持 PEM 文件（PKCS#8 / PKCS#1），或不带头尾的 base64 私钥。"""
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        raise ConfigError("缺少依赖 cryptography，请先执行：pip install cryptography")
    if conf.get("PRIVATE_KEY_FILE"):
        path = os.path.expanduser(conf["PRIVATE_KEY_FILE"])
        if not os.path.isabs(path):
            path = os.path.join(conf["_CONFIG_DIR"], path)
        if not os.path.exists(path):
            raise ConfigError("私钥文件不存在：%s" % path)
        with open(path, "rb") as f:
            data = f.read()
    else:
        data = conf["PRIVATE_KEY"].encode("utf-8")
    try:
        if b"-----BEGIN" in data:
            return serialization.load_pem_private_key(data, password=None)
        return serialization.load_der_private_key(base64.b64decode(b"".join(data.split())), password=None)
    except Exception as e:
        raise ConfigError("私钥解析失败（需为未加密的 RSA 私钥）：%s" % type(e).__name__)


def rsa_sign(private_key, text):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    signature = private_key.sign(text.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("ascii")


def java_url_encode(value):
    """与 Java URLEncoder.encode(UTF-8) 一致：空格编码为 +，保留 * - . _"""
    return urllib.parse.quote_plus(value, safe="*").replace("~", "%7E")


def build_sign_text(method, sign_uri, epoch, body_text, query_string):
    text = "%s&%s&%s&" % (method, sign_uri, epoch)
    if body_text:
        text += body_text
    if query_string:
        text += "&" + java_url_encode(urllib.parse.unquote_plus(query_string))
    return text


def mask(value, keep=4):
    if not value:
        return value
    return value[:keep] + "...(masked)"


def call(conf, method, path, body=None, query=None, dry_run=False):
    base_url = conf["BASE_URL"].rstrip("/")
    sign_uri = urllib.parse.urlparse(base_url).path.rstrip("/") + path
    query_string = urllib.parse.urlencode(query) if query else ""
    url = base_url + path + ("?" + query_string if query_string else "")
    body_text = json.dumps(body, ensure_ascii=False, separators=(",", ":")) if body is not None else ""
    epoch = str(int(time.time()))
    sign_text = build_sign_text(method, sign_uri, epoch, body_text, query_string)

    auth = base64.b64encode(("%s:%s" % (conf["DEVELOPER_ID"], conf["API_TOKEN"])).encode("utf-8")).decode("ascii")
    signature = rsa_sign(load_private_key(conf), sign_text)
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json",
        "Authorization": "Basic " + auth,
        "F-Signature": "t=%s,v=%s" % (epoch, signature),
    }
    result = {
        "request": {
            "method": method,
            "url": url,
            "body": body,
            "sign_text": sign_text,
            "headers": {
                "Authorization": "Basic " + mask(auth),
                "F-Signature": "t=%s,v=%s" % (epoch, mask(signature)),
            },
        }
    }
    if dry_run:
        result["dry_run"] = True
        return result

    data = body_text.encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    timeout = float(conf.get("TIMEOUT_SECONDS") or 30)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw, resp_headers = resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        status, raw, resp_headers = e.code, e.read(), e.headers
    raw_text = raw.decode("utf-8", errors="replace")
    try:
        resp_body = json.loads(raw_text)
    except ValueError:
        resp_body = raw_text[:2000]
    result["response"] = {
        "http_status": status,
        "trace_id": resp_headers.get("X-Trace-Id") if resp_headers else None,
        "body": resp_body,
    }
    result["summary"] = summarize(status, resp_body)
    return result


def summarize(status, body):
    """提炼关键结果，便于汇总成表格。"""
    if not isinstance(body, dict):
        return {"success": False, "http_status": status}
    if 200 <= status < 300:
        data = body.get("data")
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict):
            return {"success": True, "http_status": status, "count": body.get("count")}
        keys = ("transaction_id", "transaction_type", "status", "origin_transaction_id", "card_id",
                "billing_amount", "billing_currency", "transaction_amount", "transaction_currency", "decline_reason")
        summary = {"success": True, "http_status": status}
        summary.update({k: data[k] for k in keys if data.get(k) is not None})
        if data.get("fee_details"):
            summary["fees"] = ", ".join("%s %s %s" % (f.get("type"), f.get("amount"), f.get("currency"))
                                        for f in data["fee_details"])
        return summary
    return {"success": False, "http_status": status, "code": body.get("code"), "message": body.get("message")}


def add_amount_args(p, amount_required=False):
    p.add_argument("--amount", required=amount_required, help="账单金额（卡币种），如 10.00")
    p.add_argument("--currency", help="账单币种，只能是卡币种，可不传")
    p.add_argument("--txn-amount", help="交易金额（商户币种），跨币种时必填")
    p.add_argument("--txn-currency", help="交易币种（商户币种），如 HKD；不传默认同卡币种或原授权币种")


def add_merchant_args(p):
    p.add_argument("--merchant-name", help="商家名称，默认 MOCK MERCHANT")
    p.add_argument("--merchant-desc", help="商家描述")
    p.add_argument("--mcc", help="商家 MCC，4 位数字，默认 5411")
    p.add_argument("--country", help="商家国家/地区，ISO 3166-1 两位大写字母，如 US")


def build_body(args):
    body = {"transaction_type": {
        "auth": "AUTH", "reversal": "AUTH_REVERSAL", "settle": "SETTLE", "refund": "REFUND"}[args.command]}
    if getattr(args, "card_id", None):
        body["card_id"] = int(args.card_id)
    if getattr(args, "origin", None):
        body["origin_transaction_id"] = args.origin
    for arg, field in (("amount", "billing_amount"), ("currency", "billing_currency"),
                       ("txn_amount", "transaction_amount"), ("txn_currency", "transaction_currency")):
        if getattr(args, arg, None):
            body[field] = getattr(args, arg)
    if getattr(args, "fail", False):
        body["status"] = "failed"
        if args.decline_reason:
            body["decline_reason"] = args.decline_reason
    merchant = {}
    for arg, field in (("merchant_name", "merchant_name"), ("merchant_desc", "merchant_description"),
                       ("mcc", "mcc"), ("country", "country_code")):
        if getattr(args, arg, None):
            merchant[field] = getattr(args, arg)
    if merchant:
        body["merchant"] = merchant
    return body


def main():
    parser = argparse.ArgumentParser(description="MarsWallex 测试环境模拟卡交易")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="配置文件路径，默认 config/config.env")
    parser.add_argument("--dry-run", action="store_true", help="只生成签名原文和请求，不发送")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("auth", help="授权（消费）")
    p.add_argument("--card-id", required=True, help="卡 ID")
    add_amount_args(p, amount_required=True)
    p.add_argument("--fail", action="store_true", help="模拟授权失败")
    p.add_argument("--decline-reason", help="拒绝原因，配合 --fail 使用")
    add_merchant_args(p)

    p = sub.add_parser("reversal", help="授权撤销")
    p.add_argument("--origin", required=True, help="原授权交易单号")

    p = sub.add_parser("settle", help="结算")
    p.add_argument("--card-id", required=True, help="卡 ID")
    p.add_argument("--origin", help="原授权交易单号；不传表示无授权直接结算")
    add_amount_args(p)
    add_merchant_args(p)

    p = sub.add_parser("refund", help="退款")
    p.add_argument("--card-id", required=True, help="卡 ID")
    p.add_argument("--origin", help="原授权交易单号；不传表示无原交易的直接退款")
    add_amount_args(p, amount_required=True)
    add_merchant_args(p)

    p = sub.add_parser("raw", help="直接发送自定义请求体到模拟交易接口")
    p.add_argument("--json", required=True, help="请求体 JSON 字符串")

    p = sub.add_parser("query", help="按交易单号查询交易")
    p.add_argument("--transaction-id", required=True, help="交易单号")
    p.add_argument("--kind", choices=sorted(QUERY_PATHS), required=True,
                   help="authorization：授权与撤销；settlement：结算与退款")
    p.add_argument("--days", type=int, default=30, help="查询最近多少天，默认 30")

    args = parser.parse_args()
    try:
        conf = load_config(args.config)
        if args.command == "query":
            now = int(time.time())
            query = [("transaction_id", args.transaction_id), ("page_no", "1"), ("page_size", "10"),
                     ("start_time", str(now - args.days * 86400)), ("end_time", str(now))]
            result = call(conf, "GET", QUERY_PATHS[args.kind], query=query, dry_run=args.dry_run)
        else:
            body = json.loads(args.json) if args.command == "raw" else build_body(args)
            result = call(conf, "POST", MOCK_PATH, body=body, dry_run=args.dry_run)
    except ConfigError as e:
        print(json.dumps({"error": "config", "message": str(e)}, ensure_ascii=False, indent=2))
        return EXIT_CONFIG
    except ValueError as e:
        print(json.dumps({"error": "argument", "message": str(e)}, ensure_ascii=False, indent=2))
        return EXIT_CONFIG
    except (urllib.error.URLError, OSError) as e:
        print(json.dumps({"error": "network", "message": str(e)}, ensure_ascii=False, indent=2))
        return EXIT_NETWORK
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
