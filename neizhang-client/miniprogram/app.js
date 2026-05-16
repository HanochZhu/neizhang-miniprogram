App({
  globalData: {
    // 开发者工具里用 127.0.0.1 比 localhost 更稳；真机请改为电脑局域网 IP
    serverUrl: 'http://127.0.0.1:8000',
    token: null,
    userInfo: null
  },

  onLaunch() {
    // Check if already logged in
    const token = wx.getStorageSync('token')
    if (token) {
      this.globalData.token = token
      this.globalData.userInfo = wx.getStorageSync('userInfo')
    }
  },

  checkLogin() {
    if (!this.globalData.token) {
      wx.redirectTo({ url: '/pages/login/login' })
      return false
    }
    return true
  },

  setLogin(token, userInfo) {
    this.globalData.token = token
    this.globalData.userInfo = userInfo
    wx.setStorageSync('token', token)
    wx.setStorageSync('userInfo', userInfo)
  },

  logout() {
    this.globalData.token = null
    this.globalData.userInfo = null
    wx.removeStorageSync('token')
    wx.removeStorageSync('userInfo')
    wx.redirectTo({ url: '/pages/login/login' })
  },

  /** 记账成功后通知财务页刷新（由 main 页挂载的 financial-window 处理） */
  refreshFinanceData() {
    const pages = getCurrentPages()
    if (!pages.length) return
    const page = pages[pages.length - 1]
    const finance = page.selectComponent && page.selectComponent('#financeWin')
    if (finance && typeof finance.loadData === 'function') {
      finance.loadData()
    }
  }
})
