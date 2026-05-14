const app = getApp()

const request = (options) => {
  return new Promise((resolve, reject) => {
    const token = app.globalData.token
    const headers = {
      'Content-Type': 'application/json'
    }
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    wx.request({
      url: app.globalData.serverUrl + options.url,
      method: options.method || 'GET',
      data: options.data,
      header: headers,
      enableChunked: options.enableChunked || false,
      timeout: options.timeout != null ? options.timeout : 60000,
      success: (res) => {
        if (res.statusCode === 401) {
          app.logout()
          reject(new Error('未登录'))
        } else if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          reject(new Error(res.data.detail || '请求失败'))
        }
      },
      fail: (err) => {
        const msg = err.errMsg || ''
        let hint = msg
        if (/timeout|timed out/i.test(msg)) {
          hint =
            '请求超时：请确认后端已启动(8000)、serverUrl 用 127.0.0.1 或局域网 IP，并在「详情-本地设置」勾选不校验合法域名'
        } else if (/fail ssl|https/i.test(msg)) {
          hint = '请使用 http 访问本机后端或检查合法域名设置'
        }
        reject(new Error(hint))
      }
    })
  })
}

module.exports = {
  get: (url, data) => request({ url, method: 'GET', data }),
  post: (url, data) => request({ url, method: 'POST', data }),
  request
}
