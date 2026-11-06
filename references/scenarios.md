# 常见用例

`<卡ID>` 替换为测试卡 ID；`<A1>` 等表示前面步骤返回的 `summary.transaction_id`。
命令都在 `scripts/` 目录下执行，金额按卡币种填写。

## 1. 消费成功并全额结算

最常见的一笔刷卡消费：先授权冻结，再结算扣款。

| 步骤 | 命令 | 预期 |
| ---- | ---- | ---- |
| 1 | `python3 mock_txn.py auth --card-id <卡ID> --amount 10.00` | `AUTH` / `approved`，记下 `<A1>`；卡可用余额减少 10.00 |
| 2 | `python3 mock_txn.py settle --card-id <卡ID> --origin <A1>` | `SETTLE` / `approved`，金额沿用授权；冻结释放并扣款 10.00 |

Webhook：步骤 1 `AUTH_EVENT`，步骤 2 `SETTLE_EVENT`。

## 2. 部分结算、多次结算

酒店、加油等场景，一笔授权分多次清算。

| 步骤 | 命令 | 预期 |
| ---- | ---- | ---- |
| 1 | `python3 mock_txn.py auth --card-id <卡ID> --amount 10.00` | `approved`，记下 `<A1>` |
| 2 | `python3 mock_txn.py settle --card-id <卡ID> --origin <A1> --amount 6.00` | `approved`；整笔授权的冻结释放，扣款 6.00 |
| 3 | `python3 mock_txn.py settle --card-id <卡ID> --origin <A1> --amount 3.00` | `approved`；直接扣款 3.00 |
| 4 | `python3 mock_txn.py settle --card-id <卡ID> --origin <A1>` | 400 `billing_amount is required when the authorization has been partially settled` |

## 3. 授权失败

模拟卡组织拒绝交易，例如余额不足。

| 步骤 | 命令 | 预期 |
| ---- | ---- | ---- |
| 1 | `python3 mock_txn.py auth --card-id <卡ID> --amount 10.00 --fail --decline-reason "Insufficient funds"` | HTTP 200，`status` 为 `failed`，`decline_reason` 为 `Insufficient funds`；不冻结余额，可能收取失败手续费 |

Webhook：`AUTH_EVENT`，`status=failed`。

## 4. 授权后撤销

商户取消订单，授权被撤销，冻结释放。

| 步骤 | 命令 | 预期 |
| ---- | ---- | ---- |
| 1 | `python3 mock_txn.py auth --card-id <卡ID> --amount 5.00` | `approved`，记下 `<A1>` |
| 2 | `python3 mock_txn.py reversal --origin <A1>` | `AUTH_REVERSAL` / `approved`，`origin_transaction_id=<A1>`；冻结释放 |
| 3 | `python3 mock_txn.py settle --card-id <卡ID> --origin <A1>` | 400 `Authorization has been reversed` |

Webhook：步骤 1、2 都是 `AUTH_EVENT`。

## 5. 无授权直接结算

部分离线交易、强制入账没有授权，直接来清算。

| 步骤 | 命令 | 预期 |
| ---- | ---- | ---- |
| 1 | `python3 mock_txn.py settle --card-id <卡ID> --amount 3.00 --merchant-name "OFFLINE STORE"` | `SETTLE` / `approved`，没有 `origin_transaction_id`；直接扣款 3.00 |

## 6. 结算后退款

用户退货，商户发起退款，可以部分退、多次退。

| 步骤 | 命令 | 预期 |
| ---- | ---- | ---- |
| 1 | `python3 mock_txn.py auth --card-id <卡ID> --amount 10.00` | `approved`，记下 `<A1>` |
| 2 | `python3 mock_txn.py settle --card-id <卡ID> --origin <A1>` | `approved` |
| 3 | `python3 mock_txn.py refund --card-id <卡ID> --origin <A1> --amount 4.00` | `REFUND` / `approved`，`origin_transaction_id=<A1>`；入账 4.00 |
| 4 | `python3 mock_txn.py reversal --origin <A1>` | 400 `Authorization has been settled`（已结算的授权只能退款） |

Webhook：退款为 `SETTLE_EVENT`，`transaction_type=REFUND`。

## 7. 无原交易的直接退款

卡组织下发的退款找不到对应的原交易。

| 步骤 | 命令 | 预期 |
| ---- | ---- | ---- |
| 1 | `python3 mock_txn.py refund --card-id <卡ID> --amount 2.00` | `REFUND` / `approved`，没有 `origin_transaction_id`；入账 2.00 |

## 8. 跨币种消费

USD 卡在港币商户消费：账单金额为卡币种，交易金额为商户币种。

| 步骤 | 命令 | 预期 |
| ---- | ---- | ---- |
| 1 | `python3 mock_txn.py auth --card-id <卡ID> --amount 10.00 --txn-amount 78.00 --txn-currency HKD --country HK` | `approved`，`transaction_currency=HKD`、`billing_currency=USD`；手续费中有 `conversionFee`（以费率配置为准）。卡开启了外汇加点时返回 400 `Unsupported card` |
| 2 | `python3 mock_txn.py settle --card-id <卡ID> --origin <A1>` | `approved`，金额与币种沿用授权 |

## 9. 跨境消费

商户国家与卡产品地区不同，按跨境交易计费。

| 步骤 | 命令 | 预期 |
| ---- | ---- | ---- |
| 1 | `python3 mock_txn.py auth --card-id <卡ID> --amount 5.00 --merchant-name "US STORE" --mcc 5311 --country US` | `approved`，`merchant.country_code=US`；卡产品地区不是 US 时，手续费中有 `crossBorderTransactionFee`（以费率配置为准） |
| 2 | `python3 mock_txn.py reversal --origin <A1>` | `approved`，释放冻结 |

## 10. 查询核对

| 命令 | 用途 |
| ---- | ---- |
| `python3 mock_txn.py query --kind authorization --transaction-id <授权或撤销单号>` | 查授权、撤销 |
| `python3 mock_txn.py query --kind settlement --transaction-id <结算或退款单号>` | 查结算、退款 |

## 11. 常见错误演练

用于验证自己系统对错误响应的处理。

| 命令 | 预期 |
| ---- | ---- |
| `python3 mock_txn.py raw --json '{"card_id":<卡ID>,"billing_amount":"1.00"}'` | 400 `transaction_type is required` |
| `python3 mock_txn.py auth --card-id <卡ID> --amount 0` | 400 `billing_amount must be greater than 0` |
| `python3 mock_txn.py auth --card-id <卡ID> --amount 1.00 --txn-currency HKD` | 400 `transaction_amount is required when transaction_currency differs from billing_currency` |
| `python3 mock_txn.py reversal --origin 000000000000000000` | 404 `Transaction not found` |
| `python3 mock_txn.py auth --card-id 1 --amount 1.00` | 404 `Card not found` |
