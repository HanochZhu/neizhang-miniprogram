const app = getApp()
const api = require('./api')

const login = (code) => {
  return api.post('/api/v1/auth/login', { code })
}

const phoneLogin = (phone, name) => {
  return api.post('/api/v1/auth/phone-login', { phone, name })
}

const getToken = () => {
  return app.globalData.token
}

const isLoggedIn = () => {
  return !!app.globalData.token
}

module.exports = {
  login,
  phoneLogin,
  getToken,
  isLoggedIn
}
