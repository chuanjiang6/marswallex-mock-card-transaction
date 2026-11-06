# 不用脚本时的签名方法

签名规则见 `api.md`「签名规则」。以下两种方式与 `scripts/mock_txn.py` 生成的签名一致。

## Apifox / Postman 前置脚本

1. 在环境变量中配置：
   - `base_url`：`https://api.feibeiglobal-test.com/portal/api`
   - `developer_id`、`api_token`
   - `private_key`：PEM 格式私钥，包含 `-----BEGIN PRIVATE KEY-----` 头尾（PKCS#1 的 `BEGIN RSA PRIVATE KEY` 也可以）
2. 接口地址填 `{{base_url}}/v1/card/mock-transactions`，Body 选 raw / JSON。
3. 在项目级或接口级「前置操作」添加「自定义脚本」：

```javascript
const rs = require('jsrsasign');

const developerId = pm.environment.get('developer_id');
const apiToken = pm.environment.get('api_token');
const privateKey = pm.environment.get('private_key');

const epoch = Math.floor(Date.now() / 1000).toString();
const method = pm.request.method.toUpperCase();
const path = pm.request.url.getPath(); // 含 /portal/api
const body = pm.request.body && pm.request.body.raw ? pm.variables.replaceIn(pm.request.body.raw) : '';
const query = pm.request.url.getQueryString();

let signText = `${method}&${path}&${epoch}&${body}`;
if (query) {
    // 与 Java URLEncoder 一致：空格编码为 +
    signText += '&' + encodeURIComponent(decodeURIComponent(query)).replace(/%20/g, '+');
}

const sig = new rs.KJUR.crypto.Signature({ alg: 'SHA256withRSA' });
sig.init(rs.KEYUTIL.getKey(privateKey));
sig.updateString(signText);

const auth = CryptoJS.enc.Base64.stringify(CryptoJS.enc.Utf8.parse(`${developerId}:${apiToken}`));
pm.request.headers.upsert({ key: 'Authorization', value: `Basic ${auth}` });
pm.request.headers.upsert({ key: 'F-Signature', value: `t=${epoch},v=${rs.hextob64(sig.sign())}` });
```

注意：

- 签名后 Apifox 不能再改写请求体，不要开启 JSON 自动美化。
- 使用 Apifox 云端发送时出口 IP 是 Apifox 的，会返回 `The ip is not authorized`；请用桌面端本地发送，或把出口 IP 加入白名单。
- 查询串中含 `! ' ( ) ~` 等字符时，JS 与 Java 的编码结果不同，会导致验签失败；模拟交易接口没有查询串，不受影响。

## curl + openssl

```bash
DEVELOPER_ID=<developer_id>
API_TOKEN=<api_token>
PRIVATE_KEY=./merchant_private.pem
BASE=https://api.feibeiglobal-test.com
URI=/portal/api/v1/card/mock-transactions
BODY='{"transaction_type":"AUTH","card_id":<卡ID>,"billing_amount":"1.00"}'

T=$(date +%s)
SIG=$(printf '%s' "POST&${URI}&${T}&${BODY}" | openssl dgst -sha256 -sign "$PRIVATE_KEY" | base64 | tr -d '\n')
AUTH=$(printf '%s' "${DEVELOPER_ID}:${API_TOKEN}" | base64 | tr -d '\n')

curl -s -X POST "${BASE}${URI}" \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -H "Authorization: Basic ${AUTH}" \
  -H "F-Signature: t=${T},v=${SIG}" \
  -d "$BODY"
```

`-d "$BODY"` 发送的内容必须与签名时的 `BODY` 完全相同。
