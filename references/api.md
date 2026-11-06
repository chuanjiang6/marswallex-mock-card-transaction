# 模拟卡交易接口说明

## 接口

`POST {BASE_URL}/v1/card/mock-transactions`

- 测试环境 `BASE_URL`：`https://api.feibeiglobal-test.com/portal/api`
- `Content-Type: application/json;charset=UTF-8`
- 鉴权与签名与其他 OpenAPI 接口相同，见下文「签名规则」。

## 签名规则

| 请求头 | 格式 |
| ------ | ---- |
| `Authorization` | `Basic ` + base64(`developer_id:api_token`) |
| `F-Signature` | `t={时间戳},v={签名}`；时间戳为秒级 Unix 时间，与服务器相差不得超过 300 秒 |

签名 = base64(SHA256withRSA(商户私钥, 签名原文))，签名原文：

```
METHOD&URI&时间戳&请求体[&URL编码后的查询串]
```

- `URI` 包含 context-path，例如 `/portal/api/v1/card/mock-transactions`。
- 请求体与实际发送的字节完全一致，签名后不能再格式化 JSON。
- 没有请求体时保留末尾的 `&`，例如 `GET&/portal/api/v1/xxx&1700000000&`；有查询串时为 `GET&URI&时间戳&&查询串`。
- 查询串先解码再按 Java `URLEncoder`（UTF-8）编码：空格编码为 `+`，`*` `-` `.` `_` 不编码。

示例：

```
POST&/portal/api/v1/card/mock-transactions&1793945235&{"transaction_type":"AUTH","card_id":261102000000000036,"billing_amount":"0.50"}
```

## 请求字段

| 字段 | 类型 | 说明 |
| ---- | ---- | ---- |
| `transaction_type` | string | 必填。`AUTH` 授权、`AUTH_REVERSAL` 授权撤销、`SETTLE` 结算、`REFUND` 退款 |
| `card_id` | integer | 卡 ID。`AUTH`、`SETTLE`、`REFUND` 必填 |
| `origin_transaction_id` | string | 原授权交易单号，最长 32 位。`AUTH_REVERSAL` 必填；`SETTLE`、`REFUND` 可选，不传表示无原授权 |
| `billing_amount` | string | 账单金额，卡币种，最多 8 位整数、2 位小数，大于 0。`AUTH`、`REFUND` 必填；`SETTLE` 无原授权时必填，有原授权时首次结算不传默认等于授权金额，部分结算后必填 |
| `billing_currency` | string | 账单币种，只能是卡币种，可不传 |
| `transaction_amount` | string | 交易金额，商户币种。交易币种与卡币种不同时必填；相同时可不传，传则必须等于 `billing_amount` |
| `transaction_currency` | string | 交易币种（ISO 4217）。不传时有原授权取原授权币种，否则取卡币种 |
| `status` | string | 仅 `AUTH` 生效：`approved`（默认）或 `failed` |
| `decline_reason` | string | 仅 `AUTH` 且 `status=failed` 时生效，最长 200，默认 `Mock declined` |
| `merchant` | object | 商家信息，仅 `AUTH` 和无原授权的 `SETTLE`、`REFUND` 生效；有原授权时沿用原授权的商家 |
| `merchant.merchant_name` | string | 默认 `MOCK MERCHANT`，最长 100 |
| `merchant.merchant_description` | string | 最长 200 |
| `merchant.mcc` | string | 4 位数字，默认 `5411` |
| `merchant.country_code` | string | ISO 3166-1 两位大写字母；与卡产品地区不同时按跨境交易计费 |

## 业务规则

- 同一笔授权可以多次结算。第一次结算释放整笔授权的冻结，并按结算金额扣款；之后的结算直接扣款。
- 已结算过的授权不能撤销，只能退款。已撤销或失败的授权不能结算、不能撤销。
- 结算、退款金额不受原授权金额限制。
- 卡开启了外汇加点时，跨币种交易返回 `Unsupported card`。
- 每次调用都会生成新的交易，没有幂等；重复调用会重复记账。
- 不校验卡状态，冻结卡、注销卡也会按请求记账，与卡组织强制授权、强制结算的行为一致。

## 响应

HTTP 200 时：

```json
{
  "data": { ... }
}
```

`data` 结构与交易查询接口单条数据一致：

- `AUTH`、`AUTH_REVERSAL` 返回授权交易，同 `GET /v1/card/transactions/authorization`。
- `SETTLE`、`REFUND` 返回结算交易，同 `GET /v1/card/transactions/settlement`。

| 字段 | 说明 |
| ---- | ---- |
| `transaction_id` | 本次生成的交易单号 |
| `transaction_type` | `AUTH` / `AUTH_REVERSAL` / `SETTLE` / `REFUND` |
| `status` | `approved` / `failed` / `pending` |
| `origin_transaction_id` | 原授权单号（撤销、有原授权的结算和退款返回） |
| `card_id` | 卡 ID，字符串 |
| `billing_amount` / `billing_currency` | 账单金额、币种（卡币种）；金额去掉末尾的 0，如 `"1"`、`"7.8"` |
| `transaction_amount` / `transaction_currency` | 交易金额、币种（商户币种） |
| `auth_code` | 授权码（授权交易） |
| `decline_reason` | 拒绝原因（授权失败时） |
| `merchant` | `merchant_name`、`merchant_description`、`mcc`、`country_code` |
| `create_time` / `transaction_time` | Unix 秒 |
| `fee_details` | 手续费明细：`amount`、`currency`、`type`（如 `transactionFee`、`gatewayFee`、`smallTransactionFee`、`conversionFee`、`crossBorderTransactionFee`、`failedFee`、`discardFee`、`refundFee`） |
| `arn`、`auth_transaction_id` | 仅结算交易返回，沿用结算查询接口的结构 |

值为 null 的字段不返回。

失败时：

```json
{ "code": "INVALID_PARAMETER", "message": "card_id is required" }
```

| HTTP | code | 场景 |
| ---- | ---- | ---- |
| 400 | `INVALID_PARAMETER` | 参数格式、必填、币种、原授权状态等校验失败 |
| 401 | `UNAUTHORIZED` | 认证信息或签名错误、IP 未授权 |
| 404 | `RESOURCE_NOT_FOUND` | 卡或原交易不存在、不属于当前商户（`Card not found`、`This card not exist`、`Transaction not found`） |
| 500 | `UNEXPECTED_ERROR` | 平台处理异常，交易可能已部分处理；不要直接重试，记录响应头 `X-Trace-Id` 联系 MarsWallex |

## Webhook

| 交易类型 | Webhook topic |
| -------- | ------------- |
| `AUTH`、`AUTH_REVERSAL` | `AUTH_EVENT` |
| `SETTLE`、`REFUND` | `SETTLE_EVENT` |

需要在开放平台订阅对应事件并配置接收地址。

## 查询交易

```
GET {BASE_URL}/v1/card/transactions/authorization?transaction_id=xxx&page_no=1&page_size=10&start_time=<秒>&end_time=<秒>
GET {BASE_URL}/v1/card/transactions/settlement?transaction_id=xxx&page_no=1&page_size=10&start_time=<秒>&end_time=<秒>
```

`start_time`、`end_time`、`page_no`、`page_size` 必填。脚本的 `query` 命令默认查最近 30 天。
