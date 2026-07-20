const {
  API_BASE_URL,
  TARGET_MAX_SIZE_OPTIONS,
  DEFAULT_TARGET_MAX_SIZE,
  SIMILAR_COLOR_LEVELS,
  DEFAULT_SIMILAR_COLOR_DISTANCE
} = require("../../config")

Page({
  data: {
    serviceStatus: "checking",
    serviceStatusText: "连接中",
    imagePath: "",
    imageName: "",
    imageSizeText: "",
    imageWidth: 0,
    imageHeight: 0,
    sizeOptions: TARGET_MAX_SIZE_OPTIONS,
    maxSize: DEFAULT_TARGET_MAX_SIZE,
    unlimitedColors: false,
    colorLimit: 10,
    mergeOptions: SIMILAR_COLOR_LEVELS,
    mergeDistance: DEFAULT_SIMILAR_COLOR_DISTANCE,
    advancedOpen: false,
    outlineSimplify: true,
    brightDetailRecovery: true,
    sourceCoverageRecovery: true,
    nearWhiteCleanup: true,
    submitting: false,
    uploadProgress: 0,
    errorMessage: ""
  },

  onShow() {
    if (!this.data.submitting) this.checkService()
  },

  checkService() {
    this.setData({ serviceStatus: "checking", serviceStatusText: "连接中" })
    wx.request({
      url: `${API_BASE_URL}/api/health`,
      timeout: 3000,
      success: (response) => {
        const online = response.statusCode === 200 && response.data.status === "ok"
        this.setData({
          serviceStatus: online ? "online" : "offline",
          serviceStatusText: online ? "服务正常" : "服务未启动"
        })
      },
      fail: () => {
        this.setData({ serviceStatus: "offline", serviceStatusText: "服务未启动" })
      }
    })
  },

  chooseImage() {
    wx.chooseMedia({
      count: 1,
      mediaType: ["image"],
      sourceType: ["album", "camera"],
      sizeType: ["original"],
      success: (result) => {
        const file = result.tempFiles[0]
        const path = file.tempFilePath
        const normalizedPath = path.replace(/\\/g, "/")
        const name = normalizedPath.split("/").pop() || "已选择图片"
        this.setData({
          imagePath: path,
          imageName: name,
          imageSizeText: this.formatBytes(file.size || 0),
          errorMessage: ""
        })
        wx.getImageInfo({
          src: path,
          success: (info) => {
            this.setData({ imageWidth: info.width, imageHeight: info.height })
          }
        })
      }
    })
  },

  formatBytes(bytes) {
    if (!bytes) return "未知大小"
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  },

  selectMaxSize(event) {
    this.setData({ maxSize: Number(event.currentTarget.dataset.value) })
  },

  toggleUnlimitedColors(event) {
    this.setData({ unlimitedColors: event.detail.value })
  },

  changeColorLimit(event) {
    this.setData({ colorLimit: Number(event.detail.value) })
  },

  selectMergeDistance(event) {
    this.setData({ mergeDistance: Number(event.currentTarget.dataset.value) })
  },

  toggleAdvanced() {
    this.setData({ advancedOpen: !this.data.advancedOpen })
  },

  changeBoolean(event) {
    const field = event.currentTarget.dataset.field
    this.setData({ [field]: event.detail.value })
  },

  responseMessage(response) {
    try {
      const payload = typeof response.data === "string" ? JSON.parse(response.data) : response.data
      return payload.detail || "生成失败，请稍后重试。"
    } catch (error) {
      return "生成失败，请检查本地服务。"
    }
  },

  generatePattern() {
    if (!this.data.imagePath || this.data.submitting) return
    if (this.data.serviceStatus !== "online") {
      this.checkService()
      this.setData({ errorMessage: "本地服务未启动，请先运行 python -m uvicorn server.main:app --reload。" })
      return
    }

    this.setData({ submitting: true, uploadProgress: 1, errorMessage: "" })
    const uploadTask = wx.uploadFile({
      url: `${API_BASE_URL}/api/v1/patterns`,
      filePath: this.data.imagePath,
      name: "file",
      timeout: 120000,
      formData: {
        max_size: String(this.data.maxSize),
        color_limit: String(this.data.unlimitedColors ? 0 : this.data.colorLimit),
        global_color_merge_distance: String(this.data.mergeDistance),
        outline_simplify: String(this.data.outlineSimplify),
        bright_detail_recovery: String(this.data.brightDetailRecovery),
        source_coverage_recovery: String(this.data.sourceCoverageRecovery),
        near_white_cleanup: String(this.data.nearWhiteCleanup),
        title: "拼豆图纸"
      },
      success: (response) => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          this.setData({ errorMessage: this.responseMessage(response) })
          return
        }
        try {
          const result = JSON.parse(response.data)
          getApp().globalData.latestPattern = result
          wx.setStorageSync("latestPattern", result)
          wx.navigateTo({ url: "/pages/result/result" })
        } catch (error) {
          this.setData({ errorMessage: "服务返回的数据无法读取。" })
        }
      },
      fail: (error) => {
        const timeout = (error.errMsg || "").includes("timeout")
        this.setData({
          errorMessage: timeout ? "生成超时，请降低图片尺寸后重试。" : "无法连接本地生成服务。"
        })
        this.checkService()
      },
      complete: () => {
        this.setData({ submitting: false, uploadProgress: 0 })
      }
    })

    uploadTask.onProgressUpdate((progress) => {
      const value = progress.progress >= 100 ? 96 : Math.max(1, progress.progress)
      this.setData({ uploadProgress: value })
    })
  }
})
