Page({
  data: {
    result: null,
    summary: [],
    shortJobId: "",
    activeTab: "pattern",
    currentImageUrl: "",
    imageLoading: true,
    saving: false,
    statusBarHeight: 20,
    navigationBarHeight: 44,
    navigationTotalHeight: 64
  },

  onLoad() {
    this.setupNavigation()
    const appResult = getApp().globalData.latestPattern
    const result = appResult || wx.getStorageSync("latestPattern")
    if (!result || !result.pattern_url) return
    const total = result.bead_count || 1
    const summary = (result.summary || []).map((item) => ({
      ...item,
      share: ((item.count / total) * 100).toFixed(1)
    }))
    this.setData({
      result,
      summary,
      shortJobId: (result.job_id || "").slice(0, 8).toUpperCase(),
      currentImageUrl: result.pattern_url
    })
  },

  setupNavigation() {
    const windowInfo = wx.getWindowInfo()
    const menuButton = wx.getMenuButtonBoundingClientRect()
    const statusBarHeight = windowInfo.statusBarHeight || 20
    const menuGap = Math.max(4, menuButton.top - statusBarHeight)
    const navigationBarHeight = menuButton.height + menuGap * 2
    this.setData({
      statusBarHeight,
      navigationBarHeight,
      navigationTotalHeight: statusBarHeight + navigationBarHeight
    })
  },

  selectTab(event) {
    const activeTab = event.currentTarget.dataset.tab
    const currentImageUrl = activeTab === "pattern" ? this.data.result.pattern_url : this.data.result.rgb_url
    this.setData({ activeTab, currentImageUrl, imageLoading: true })
  },

  imageLoaded() {
    this.setData({ imageLoading: false })
  },

  previewCurrent() {
    if (!this.data.currentImageUrl) return
    wx.previewImage({
      current: this.data.currentImageUrl,
      urls: [this.data.result.pattern_url, this.data.result.rgb_url]
    })
  },

  saveCurrent() {
    if (!this.data.currentImageUrl || this.data.saving) return
    this.setData({ saving: true })
    wx.showLoading({ title: "正在保存", mask: true })
    wx.downloadFile({
      url: this.data.currentImageUrl,
      success: (download) => {
        if (download.statusCode !== 200) {
          wx.showToast({ title: "图片下载失败", icon: "none" })
          return
        }
        this.saveToAlbum(download.tempFilePath)
      },
      fail: () => {
        wx.showToast({ title: "图片下载失败", icon: "none" })
      },
      complete: () => {
        wx.hideLoading()
        this.setData({ saving: false })
      }
    })
  },

  saveToAlbum(filePath) {
    wx.saveImageToPhotosAlbum({
      filePath,
      success: () => wx.showToast({ title: "已保存到相册", icon: "success" }),
      fail: (error) => {
        const denied = (error.errMsg || "").includes("auth")
        if (!denied) {
          wx.showToast({ title: "保存失败", icon: "none" })
          return
        }
        wx.showModal({
          title: "需要相册权限",
          content: "请在设置中允许保存图片到相册。",
          confirmText: "打开设置",
          success: (modal) => {
            if (modal.confirm) wx.openSetting()
          }
        })
      }
    })
  },

  copySummary() {
    if (!this.data.summary.length) return
    const lines = this.data.summary.map((item) => `${item.code} ${item.count}颗`)
    wx.setClipboardData({
      data: lines.join("\n"),
      success: () => wx.showToast({ title: "用量已复制", icon: "success" })
    })
  },

  backToEdit() {
    if (getCurrentPages().length > 1) {
      wx.navigateBack()
    } else {
      wx.reLaunch({ url: "/pages/index/index" })
    }
  },

  onShareAppMessage() {
    return {
      title: "Bean Pudding 拼豆图纸",
      path: "/pages/index/index"
    }
  }
})
