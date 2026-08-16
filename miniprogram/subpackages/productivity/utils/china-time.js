// 统一复用主包的 Asia/Shanghai 时区实现，避免主包/分包出现两套日期口径。
module.exports = require('../../../utils/china-time')
