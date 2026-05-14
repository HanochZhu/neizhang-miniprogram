const app = getApp()
const api = require('../../services/api')

Component({
  data: {
    messages: [],
    inputText: '',
    streaming: false,
    streamText: '',
    scrollToView: '',
    currentAssistantMsg: null
  },

  lifetimes: {
    attached() {
      this.loadHistory()
    }
  },

  methods: {
    onInput(e) {
      this.setData({ inputText: e.detail.value })
    },

    async sendMessage() {
      const text = this.data.inputText.trim()
      if (!text || this.data.streaming) return

      // Add user message
      const userMsg = { id: Date.now(), role: 'user', content: text }
      const messages = [...this.data.messages, userMsg]

      this.setData({
        messages,
        inputText: '',
        streaming: true,
        streamText: '',
        scrollToView: 'msg-bottom'
      })

      try {
        await this.streamChat(text)
      } catch (err) {
        wx.showToast({ title: err.message || '发送失败', icon: 'none' })
        this.setData({ streaming: false })
      }
    },

    streamChat(message) {
      return new Promise((resolve, reject) => {
        const token = app.globalData.token
        const that = this

        const task = wx.request({
          url: app.globalData.serverUrl + '/api/v1/chat/send',
          method: 'POST',
          header: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          data: { message },
          enableChunked: true,
          responseType: 'text',
          success: () => {},
          fail: (err) => {
            that.setData({ streaming: false })
            reject(new Error('请求失败: ' + err.errMsg))
          }
        })

        // Handle chunked response
        let buffer = ''
        task.onChunkReceived((res) => {
          try {
            buffer += res.data
            // Process complete SSE events
            const lines = buffer.split('\n\n')
            buffer = lines.pop() || '' // Keep incomplete chunk

            for (const line of lines) {
              if (!line.trim() || !line.startsWith('data: ')) continue
              const jsonStr = line.slice(6) // Remove 'data: ' prefix
              try {
                const event = JSON.parse(jsonStr)
                that.handleSSEEvent(event)
              } catch (e) {
                console.warn('Failed to parse SSE:', jsonStr)
              }
            }
          } catch (e) {
            console.error('Chunk processing error:', e)
          }
        })

        // We need to poll for completion since wx.request doesn't have a promise-based chunked API
        // Use a combination approach
        task.onHeadersReceived(() => {
          // Headers received, continue handling chunks
        })
      })
    },

    handleSSEEvent(event) {
      switch (event.type) {
        case 'text_delta':
          const newStreamText = this.data.streamText + event.content
          this.setData({ streamText: newStreamText })
          break

        case 'tool_start':
          if (this.data.streamText) {
            // Save the text part before tool call
            const assistantMsg = {
              id: Date.now(),
              role: 'assistant',
              content: this.data.streamText,
              toolCalls: [{ name: event.tool_name, input: JSON.stringify(event.tool_input) }]
            }
            const messages = [...this.data.messages, assistantMsg]
            this.setData({ messages, streamText: '', currentAssistantMsg: assistantMsg })
          }
          break

        case 'tool_result':
          // Update last assistant message with tool result
          const msgs = this.data.messages
          const lastMsg = msgs[msgs.length - 1]
          if (lastMsg && lastMsg.toolCalls) {
            const lastTool = lastMsg.toolCalls[lastMsg.toolCalls.length - 1]
            lastTool.result = event.content
            this.setData({ messages: msgs })
          }
          break

        case 'message_stop':
          if (this.data.streamText) {
            const finalMsg = {
              id: Date.now(),
              role: 'assistant',
              content: this.data.streamText
            }
            const messages = [...this.data.messages, finalMsg]
            this.setData({ messages, streaming: false, streamText: '' })
          } else {
            this.setData({ streaming: false })
          }
          break

        case 'error':
          wx.showToast({ title: event.content || '发生错误', icon: 'none' })
          this.setData({ streaming: false })
          break
      }
    },

    async chooseFile() {
      const that = this
      wx.chooseMessageFile({
        count: 1,
        type: 'all',
        success(res) {
          const file = res.tempFiles[0]
          that.uploadFile(file)
        }
      })
    },

    async uploadFile(file) {
      wx.showLoading({ title: '上传中...' })
      const token = app.globalData.token

      wx.uploadFile({
        url: app.globalData.serverUrl + '/api/v1/files/upload',
        filePath: file.path,
        name: 'file',
        header: {
          'Authorization': `Bearer ${token}`
        },
        success: (res) => {
          wx.hideLoading()
          if (res.statusCode === 200) {
            const data = JSON.parse(res.data)
            const fileMsg = {
              id: Date.now(),
              role: 'user',
              file: { name: file.name, url: data.url }
            }
            const messages = [...this.data.messages, fileMsg]
            this.setData({ messages })
          } else {
            wx.showToast({ title: '上传失败', icon: 'none' })
          }
        },
        fail: () => {
          wx.hideLoading()
          wx.showToast({ title: '上传失败', icon: 'none' })
        }
      })
    },

    loadHistory() {
      // Could load recent chat messages from server
      // For now, show welcome message
      this.setData({
        messages: [{
          id: 1,
          role: 'assistant',
          content: '你好！我是内账助手，可以帮助你记录和管理财务收支。\n\n你可以这样跟我说话：\n- "今天午餐花了50元"\n- "查询本周的支出"\n- "本月团队收支汇总"\n\n请开始记账吧！'
        }]
      })
    }
  }
})
