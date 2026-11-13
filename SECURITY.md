# 安全策略 / Security Policy

## 支持范围

安全修复优先面向 `main` 分支和最新稳定版本。历史版本不保证获得回补；部署前请检查最新发布说明，并使用仍受支持的依赖版本。

Security fixes prioritize the `main` branch and the latest stable release. Backports to older releases are not guaranteed.

## 私密报告漏洞

请通过本仓库的 [Report a vulnerability](https://github.com/ly9098-prog/postgraduate-exam-AI/security/advisories/new) 提交私密报告。维护者需先启用 GitHub Private vulnerability reporting，该入口才可用。

如果入口不可用，请在公开 Issue 中仅请求开启私密报告渠道，不要附上漏洞细节、利用代码、凭据或用户数据。待私密渠道可用后再提交完整报告。

Use GitHub's **Report a vulnerability** to report security issues privately. If private reporting is unavailable, open an issue requesting a private reporting channel without disclosing vulnerability details, exploit code, credentials, or user data.

建议报告包含：

- 受影响的版本或提交、组件及运行环境。
- 使用测试数据的最小复现步骤，以及预期行为和实际行为。
- 漏洞影响、所需权限，以及经过脱敏的日志或截图。
- 可选的修复建议或补丁。

Please include the affected version, component, environment, minimal reproduction using test data, impact, and sanitized evidence. Suggested fixes are welcome.

## 协调披露

请在维护者确认和修复前避免公开可利用的细节。响应与修复时间取决于影响程度和维护资源，本项目不承诺固定时限。

测试应限定在自己拥有或明确获授权的环境中，避免影响在线服务或访问他人数据。若发现已泄露的凭据，请只报告位置和类型，不要验证凭据或在报告中重复粘贴。

Please coordinate disclosure with the maintainer. There is no guaranteed response or remediation deadline. Test only in environments you own or are authorized to assess; report exposed credentials by location and type without using or reproducing them.
