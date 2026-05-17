const auth = require('../../services/auth')
const app = getApp()

Page({
  data: {
    loading: false,
    phoneLoading: false,
    phone: '',
    name: ''
  },

  onLoad() {
    // Auto redirect if already logged in
    if (auth.isLoggedIn()) {
      wx.redirectTo({ url: '/pages/main/main' })
    }
  },

  wechatLogin() {
    this.setData({ loading: true })

    wx.login({
      success: async (res) => {
        if (!res.code) {
          wx.showToast({ title: '获取登录凭证失败', icon: 'none' })
          this.setData({ loading: false })
          return
        }

        try {
          const result = await auth.login(res.code)
          app.setLogin(result.token, { user_id: result.user_id, team_id: result.team_id, role: result.role || 'member' })
          wx.showToast({ title: '登录成功', icon: 'success' })
          setTimeout(() => {
            wx.redirectTo({ url: '/pages/main/main' })
          }, 500)
        } catch (err) {
          wx.showToast({ title: err.message || '登录失败', icon: 'none' })
        } finally {
          this.setData({ loading: false })
        }
      },
      fail: () => {
        wx.showToast({ title: '微信登录失败', icon: 'none' })
        this.setData({ loading: false })
      }
    })
  },

  onPhoneInput(e) {
    this.setData({ phone: e.detail.value })
  },

  onNameInput(e) {
    this.setData({ name: e.detail.value })
  },

  async phoneLogin() {
    const { phone, name } = this.data

    if (!phone || phone.length < 11) {
      wx.showToast({ title: '请输入正确的手机号', icon: 'none' })
      return
    }
    if (!name.trim()) {
      wx.showToast({ title: '请输入姓名', icon: 'none' })
      return
    }

    this.setData({ phoneLoading: true })

    try {
      const result = await auth.phoneLogin(phone, name.trim())
      app.setLogin(result.token, { user_id: result.user_id, team_id: result.team_id, role: result.role || 'member' })
      wx.showToast({ title: '登录成功', icon: 'success' })
      setTimeout(() => {
        wx.redirectTo({ url: '/pages/main/main' })
      }, 500)
    } catch (err) {
      wx.showToast({ title: err.message || '登录失败', icon: 'none' })
    } finally {
      this.setData({ phoneLoading: false })
    }
  }
})
