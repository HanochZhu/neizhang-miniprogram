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
    this.setData({ financeRefreshNonce: Date.now() })
    const finance = this.selectComponent('#financeWin')
    if (finance && typeof finance.loadData === 'function') {
      finance.loadData()
    }
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
