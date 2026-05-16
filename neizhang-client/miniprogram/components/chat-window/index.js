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

      const userMsg = { id: Date.now(), role: 'user', content: text }
      const messages = [...this.data.messages, userMsg]

      this.setData({
        messages,
        inputText: '',
        streaming: true,
        streamText: '',
        currentAssistantMsg: null,
        scrollToView: 'msg-bottom'
      })

      try {
        await this.streamChat(text)
      } catch (err) {
        wx.showToast({ title: err.message || '发送失败', icon: 'none' })
        this.setData({ streaming: false, streamText: '', currentAssistantMsg: null })
      }
    },

    _decodeChunk(data) {
      if (data == null) return ''
      if (typeof data === 'string') return data
      if (data instanceof ArrayBuffer) {
        return new TextDecoder('utf-8').decode(new Uint8Array(data))
      }
      return String(data)
    },

    _processSSEChunk(raw) {
      if (!this._sseBuffer) this._sseBuffer = ''
      this._sseBuffer += this._decodeChunk(raw)

      const parts = this._sseBuffer.split('\n\n')
      this._sseBuffer = parts.pop() || ''

      for (const block of parts) {
        const line = block.trim()
        if (!line.startsWith('data: ')) continue
        const jsonStr = line.slice(6)
        try {
          const event = JSON.parse(jsonStr)
          this.handleSSEEvent(event)
        } catch (e) {
          console.warn('Failed to parse SSE:', jsonStr)
        }
      }
    },

    _flushSSEBuffer() {
      const rest = (this._sseBuffer || '').trim()
      this._sseBuffer = ''
      if (!rest) return
      if (rest.startsWith('data: ')) {
        try {
          const event = JSON.parse(rest.slice(6))
          this.handleSSEEvent(event)
        } catch (e) {
          console.warn('Failed to parse trailing SSE:', rest)
        }
      }
    },

    streamChat(message) {
      return new Promise((resolve, reject) => {
        const token = app.globalData.token
        const that = this
        that._sseBuffer = ''
        that._streamEnded = false

        const finish = (err) => {
          if (that._streamEnded) return
          that._streamEnded = true
          that._flushSSEBuffer()
          that.finalizeStream()
          if (err) reject(err)
          else resolve()
        }

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
          success: (res) => {
            if (res.statusCode >= 400) {
              finish(new Error(res.data?.detail || '请求失败'))
              return
            }
            if (res.data) that._processSSEChunk(res.data)
            finish()
          },
          fail: (err) => {
            that.setData({ streaming: false, streamText: '', currentAssistantMsg: null })
            finish(new Error('请求失败: ' + err.errMsg))
          }
        })

        task.onChunkReceived((res) => {
          try {
            that._processSSEChunk(res.data)
          } catch (e) {
            console.error('Chunk processing error:', e)
          }
        })
      })
    },

    _ensureAssistantToolMessage(toolName, toolInput) {
      if (this.data.currentAssistantMsg) return

      const assistantMsg = {
        id: Date.now(),
        role: 'assistant',
        content: this.data.streamText || '',
        toolCalls: [{
          name: toolName,
          input: typeof toolInput === 'string' ? toolInput : JSON.stringify(toolInput || {})
        }]
      }
      const messages = [...this.data.messages, assistantMsg]
      this.setData({
        messages,
        streamText: '',
        currentAssistantMsg: assistantMsg
      })
    },

    _appendStreamText(text) {
      if (!text) return
      this.setData({ streamText: this.data.streamText + text })
    },

    _applyToolResult(toolName, resultContent) {
      let displayText = resultContent
      try {
        const parsed = JSON.parse(resultContent)
        if (parsed.message) displayText = parsed.message
        else if (parsed.error) displayText = parsed.error
      } catch (e) {
        // keep raw string
      }

      const msgs = [...this.data.messages]
      const lastMsg = msgs[msgs.length - 1]

      if (lastMsg && lastMsg.role === 'assistant' && lastMsg.toolCalls) {
        const lastTool = lastMsg.toolCalls[lastMsg.toolCalls.length - 1]
        lastTool.result = resultContent
        if (!lastMsg.content) {
          lastMsg.content = displayText
        } else if (!lastMsg.content.includes(displayText)) {
          lastMsg.content = lastMsg.content + '\n' + displayText
        }
        this.setData({
          messages: msgs,
          streamText: displayText,
          currentAssistantMsg: lastMsg
        })
        return
      }

      this._appendStreamText(displayText)
    },

    handleSSEEvent(event) {
      switch (event.type) {
        case 'text_delta':
          this._appendStreamText(event.content || '')
          break

        case 'record_success':
          this._appendStreamText(event.content || '')
          break

        case 'tool_start':
          if (this.data.streamText) {
            const assistantMsg = {
              id: Date.now(),
              role: 'assistant',
              content: this.data.streamText,
              toolCalls: [{
                name: event.tool_name,
                input: JSON.stringify(event.tool_input || {})
              }]
            }
            const messages = [...this.data.messages, assistantMsg]
            this.setData({ messages, streamText: '', currentAssistantMsg: assistantMsg })
          } else {
            this._ensureAssistantToolMessage(event.tool_name, event.tool_input)
          }
          break

        case 'tool_result':
          this._applyToolResult(event.tool_name, event.content || '')
          break

        case 'message_stop':
          this.finalizeStream()
          break

        case 'error':
          wx.showToast({ title: event.content || '发生错误', icon: 'none' })
          this.setData({ streaming: false, streamText: '', currentAssistantMsg: null })
          break
      }
    },

    finalizeStream() {
      if (!this.data.streaming && !this.data.streamText && !this.data.currentAssistantMsg) {
        return
      }

      const msgs = [...this.data.messages]
      const streamText = (this.data.streamText || '').trim()
      const current = this.data.currentAssistantMsg

      if (current) {
        const idx = msgs.findIndex((m) => m.id === current.id)
        if (idx >= 0) {
          if (streamText && !msgs[idx].content) {
            msgs[idx].content = streamText
          } else if (streamText && msgs[idx].content && !msgs[idx].content.includes(streamText)) {
            msgs[idx].content = msgs[idx].content + '\n' + streamText
          }
        } else if (streamText || current.content) {
          msgs.push({
            id: current.id || Date.now(),
            role: 'assistant',
            content: streamText || current.content || '已完成',
            toolCalls: current.toolCalls
          })
        }
      } else if (streamText) {
        msgs.push({
          id: Date.now(),
          role: 'assistant',
          content: streamText
        })
      }

      this.setData({
        messages: msgs,
        streaming: false,
        streamText: '',
        currentAssistantMsg: null,
        scrollToView: 'msg-bottom'
      })
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
