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
    _resetStreamState() {
      this._streamBuffer = ''
      this._sseMessageStop = false
      this._streamFinalized = false
    },

    _notifyFinanceRefresh() {
      const app = getApp()
      if (app && typeof app.refreshFinanceData === 'function') {
        app.refreshFinanceData()
      }
    },

    onInput(e) {
      this.setData({ inputText: e.detail.value })
    },

    async sendMessage() {
      const text = this.data.inputText.trim()
      if (!text || this.data.streaming) return

      const userMsg = { id: Date.now(), role: 'user', content: text }
      const messages = [...this.data.messages, userMsg]

      this._resetStreamState()

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
        that._resetStreamState()

        const finish = (err) => {
          if (that._streamEnded) return
          that._streamEnded = true
          that._flushSSEBuffer()
          if (!that._sseMessageStop) {
            that.finalizeStream()
          }
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
            if (res.data && !that._sseMessageStop) {
              that._processSSEChunk(res.data)
            }
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
      this._streamBuffer = ''
      this.setData({
        messages,
        streamText: '',
        currentAssistantMsg: assistantMsg
      })
    },

    _appendStreamText(text) {
      if (!text) return
      this._streamBuffer = (this._streamBuffer || '') + text
      this.setData({ streamText: this._streamBuffer })
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
        this._streamBuffer = displayText
        this.setData({
          messages: msgs,
          streamText: displayText,
          currentAssistantMsg: lastMsg
        })
        return
      }

      this._appendStreamText(displayText)
    },

    _typeLabel(txType) {
      return txType === 'income' ? '收入' : '支出'
    },

    _attachPendingConfirm(pendingConfirm) {
      const msgs = [...this.data.messages]
      const current = this.data.currentAssistantMsg
      const streamText = (this.data.streamText || '').trim()

      if (current) {
        const idx = msgs.findIndex((m) => m.id === current.id)
        if (idx >= 0) {
          msgs[idx] = {
            ...msgs[idx],
            content: streamText || msgs[idx].content || pendingConfirm.message,
            pendingConfirm
          }
          this.setData({
            messages: msgs,
            streamText: '',
            currentAssistantMsg: msgs[idx],
            streaming: false
          })
          return
        }
      }

      msgs.push({
        id: Date.now(),
        role: 'assistant',
        content: streamText || pendingConfirm.message,
        pendingConfirm
      })
      this.setData({
        messages: msgs,
        streamText: '',
        currentAssistantMsg: null,
        streaming: false
      })
    },

    _resolvePendingConfirm(proposalId, status, extraText) {
      const msgs = [...this.data.messages]
      const idx = msgs.findIndex(
        (m) => m.pendingConfirm && m.pendingConfirm.proposalId === proposalId
      )
      if (idx < 0) return

      const msg = { ...msgs[idx] }
      msg.pendingConfirm = { ...msg.pendingConfirm, status }
      if (extraText) {
        msg.content = extraText
      }
      msgs[idx] = msg
      this.setData({ messages: msgs, currentAssistantMsg: null })
    },

    handleSSEEvent(event) {
      switch (event.type) {
        case 'text_delta':
          this._appendStreamText(event.content || '')
          break

        case 'record_success':
          this._appendStreamText(event.content || '')
          this._notifyFinanceRefresh()
          break

        case 'confirmation_required':
          this._attachPendingConfirm({
            proposalId: event.proposal_id,
            message: event.message || '请确认是否保存该笔记录',
            reason: event.reason || '',
            transaction: event.transaction || {},
            status: 'pending'
          })
          break

        case 'proposal_confirmed':
          this._resolvePendingConfirm(event.proposal_id, 'confirmed')
          this._notifyFinanceRefresh()
          break

        case 'proposal_cancelled':
          this._resolvePendingConfirm(
            event.proposal_id,
            'cancelled',
            event.content || '已取消，未保存该笔记录。'
          )
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
            this._streamBuffer = ''
            this.setData({ messages, streamText: '', currentAssistantMsg: assistantMsg })
          } else {
            this._ensureAssistantToolMessage(event.tool_name, event.tool_input)
          }
          break

        case 'tool_result':
          this._applyToolResult(event.tool_name, event.content || '')
          break

        case 'message_stop':
          if (!this._sseMessageStop) {
            this._sseMessageStop = true
            this.finalizeStream()
          }
          break

        case 'error':
          wx.showToast({ title: event.content || '发生错误', icon: 'none' })
          this.setData({ streaming: false, streamText: '', currentAssistantMsg: null })
          break
      }
    },

    onConfirmProposal(e) {
      const proposalId = e.currentTarget.dataset.proposalId
      const confirmed = e.currentTarget.dataset.confirmed === 'true' || e.currentTarget.dataset.confirmed === true
      if (!proposalId || this.data.streaming) return
      this.streamConfirm(proposalId, confirmed)
    },

    streamConfirm(proposalId, confirmed) {
      const token = app.globalData.token
      const that = this
      that._sseBuffer = ''
      that._streamEnded = false
      that._resetStreamState()
      that.setData({ streaming: true, streamText: '' })

      const finish = (err) => {
        if (that._streamEnded) return
        that._streamEnded = true
        that._flushSSEBuffer()
        that.setData({ streaming: false, streamText: '' })
        if (err) wx.showToast({ title: err.message || '操作失败', icon: 'none' })
      }

      const task = wx.request({
        url: app.globalData.serverUrl + '/api/v1/chat/confirm',
        method: 'POST',
        header: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        data: { proposal_id: proposalId, confirmed },
        enableChunked: true,
        responseType: 'text',
        success: (res) => {
          if (res.statusCode >= 400) {
            finish(new Error(res.data?.detail || '请求失败'))
            return
          }
          if (res.data && !that._sseMessageStop) {
            that._processSSEChunk(res.data)
          }
          finish()
        },
        fail: (err) => {
          finish(new Error('请求失败: ' + err.errMsg))
        }
      })

      task.onChunkReceived((res) => {
        try {
          that._processSSEChunk(res.data)
        } catch (e) {
          console.error('Confirm chunk error:', e)
        }
      })
    },

    finalizeStream() {
      if (this._streamFinalized) return

      const last = this.data.messages[this.data.messages.length - 1]
      if (last && last.pendingConfirm && last.pendingConfirm.status === 'pending') {
        this._streamFinalized = true
        this._streamBuffer = ''
        this.setData({ streaming: false, streamText: '', currentAssistantMsg: null })
        return
      }

      const streamText = (this._streamBuffer || this.data.streamText || '').trim()
      const current = this.data.currentAssistantMsg

      if (!this.data.streaming && !streamText && !current) {
        return
      }

      const msgs = [...this.data.messages]
      let updated = false

      if (current) {
        const idx = msgs.findIndex((m) => m.id === current.id)
        if (idx >= 0) {
          const existing = msgs[idx].content || ''
          if (streamText && !existing) {
            msgs[idx] = { ...msgs[idx], content: streamText }
            updated = true
          } else if (streamText && existing && !existing.includes(streamText)) {
            msgs[idx] = { ...msgs[idx], content: existing + '\n' + streamText }
            updated = true
          } else if (!existing && current.content) {
            msgs[idx] = { ...msgs[idx], content: current.content }
            updated = true
          }
        } else if (streamText || current.content) {
          msgs.push({
            id: current.id || Date.now(),
            role: 'assistant',
            content: streamText || current.content || '已完成',
            toolCalls: current.toolCalls
          })
          updated = true
        }
      } else if (streamText) {
        msgs.push({
          id: Date.now(),
          role: 'assistant',
          content: streamText
        })
        updated = true
      }

      this._streamFinalized = true
      this._streamBuffer = ''
      this.setData({
        messages: updated ? msgs : this.data.messages,
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
