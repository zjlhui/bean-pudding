// 正式发布前应替换为绑定到云托管服务的自定义 HTTPS 域名。
const API_BASE_URL = "https://bean-pudding-api-284609-10-1456095406.sh.run.tcloudbase.com"

// 用户可选的图纸最长边豆数，以及首次打开页面时的默认值。
const TARGET_MAX_SIZE_OPTIONS = [29, 52, 78]
const DEFAULT_TARGET_MAX_SIZE = 78

// 相近色统一的三个档位，value 是发送给后端的 LAB 色差阈值。
const SIMILAR_COLOR_LEVELS = [
  { label: "细节优先", value: 4 },
  { label: "均衡", value: 6 },
  { label: "精简优先", value: 8 }
]
const DEFAULT_SIMILAR_COLOR_DISTANCE = 6

module.exports = {
  API_BASE_URL,
  TARGET_MAX_SIZE_OPTIONS,
  DEFAULT_TARGET_MAX_SIZE,
  SIMILAR_COLOR_LEVELS,
  DEFAULT_SIMILAR_COLOR_DISTANCE
}
