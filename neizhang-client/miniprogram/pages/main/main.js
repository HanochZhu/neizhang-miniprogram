const app = getApp()

Page({
  data: {
    currentTab: 0,
    financeRefreshNonce: 0
  },

  onLoad() {
    if (!app.checkLogin()) return
  },

  onShow() {
    if (!app.checkLogin()) return
    if (this.data.currentTab === 1) {
      this.refreshFinanceTab()
    }
  },

  refreshFinanceTab() {
    // 更新 nonce 触发 financial-window 的 observer，锁定新截止日并请求
    this.setData({ financeRefreshNonce: Date.now() })
  },

  switchTab(e) {
    const index = parseInt(e.currentTarget.dataset.index)
    this.setData({ currentTab: index }, () => {
      if (index === 1) {
        this.refreshFinanceTab()
      }
    })
  }
})
