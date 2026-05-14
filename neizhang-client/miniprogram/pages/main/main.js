const app = getApp()

Page({
  data: {
    currentTab: 0
  },

  onLoad() {
    if (!app.checkLogin()) return
  },

  onShow() {
    if (!app.checkLogin()) return
  },

  switchTab(e) {
    const index = parseInt(e.currentTarget.dataset.index)
    this.setData({ currentTab: index })
  }
})
