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

    _isImageFile(name) {
      return /\.(png|jpe?g|gif|webp|bmp)$/i.test(name || '')
    },

    _startSSEStream(url, data, options = {}) {
      const { finalizeOnEnd = true } = options
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
          if (finalizeOnEnd && !that._sseMessageStop) {
            that.finalizeStream()
          } else if (!finalizeOnEnd) {
            that.setData({ streaming: false, streamText: '' })
          }
          if (err) reject(err)
          else resolve()
        }

        const task = wx.request({
          url: app.globalData.serverUrl + url,
          method: 'POST',
          header: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          data,
          enableChunked: true,
          responseType: 'text',
          success: (res) => {
            if (res.statusCode >= 400) {
              let detail = '请求失败'
              try {
                const body = typeof res.data === 'string' ? JSON.parse(res.data) : res.data
                detail = body?.detail || detail
              } catch (e) {
                // ignore
              }
              finish(new Error(detail))
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

    streamChat(message) {
      return this._startSSEStream('/api/v1/chat/send', { message })
    },

    analyzeImage(fileId) {
      this.setData({
        streaming: true,
        streamText: '',
        currentAssistantMsg: null,
        scrollToView: 'msg-bottom'
      })
      return this._startSSEStream('/api/v1/chat/analyze-image', { file_id: fileId })
    },

    _ensureAssistantToolMessage(toolName, toolInput) {
      if (this.data.currentAssistantMsg) return

      const assistantMsg = {
        id: Date.now(),
        role: 'assistant',
        content: (this._streamBuffer || this.data.streamText || '').trim(),
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
          this._sseMessageStop = true
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

        case 'tool_start': {
          const bufferedText = (this._streamBuffer || this.data.streamText || '').trim()
          if (bufferedText) {
            const assistantMsg = {
              id: Date.now(),
              role: 'assistant',
              content: bufferedText,
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
        }

        case 'tool_result':
          this._applyToolResult(event.tool_name, event.content || '')
          if (event.tool_name === 'add_transaction') {
            try {
              const parsed = JSON.parse(event.content || '{}')
              if (parsed.success) {
                this._notifyFinanceRefresh()
              }
            } catch (e) {
              // ignore
            }
          }
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
      this.setData({ streaming: true, streamText: '', currentAssistantMsg: null })
      return this._startSSEStream(
        '/api/v1/chat/confirm',
        { proposal_id: proposalId, confirmed },
        { finalizeOnEnd: false }
      ).catch((err) => {
        wx.showToast({ title: err.message || '操作失败', icon: 'none' })
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
        const lastMsg = msgs[msgs.length - 1]
        const needsNew =
          !lastMsg ||
          lastMsg.role === 'user' ||
          (lastMsg.role === 'assistant' && !(lastMsg.content || '').trim())
        if (needsNew) {
          msgs.push({
            id: Date.now(),
            role: 'assistant',
            content: streamText
          })
          updated = true
        } else if (lastMsg.role === 'assistant' && !(lastMsg.content || '').includes(streamText)) {
          msgs[msgs.length - 1] = {
            ...lastMsg,
            content: ((lastMsg.content || '') + '\n' + streamText).trim()
          }
          updated = true
        }
      }

      this._streamFinalized = true
      this._streamBuffer = ''
      this.setData({
        messages: updated ? msgs : this.data.messages,
        streaming: false,
        streamText: '',
        currentAssistantMsg: null,
        scrollToView: 'msg-bottom'
      }, () => {
        this.setData({ scrollToView: 'msg-bottom' })
      })
    },

    chooseFile() {
      const that = this
      wx.chooseMedia({
        count: 1,
        mediaType: ['image'],
        sourceType: ['album', 'camera'],
        success(res) {
          const item = res.tempFiles[0]
          const name = item.name || `image_${Date.now()}.jpg`
          that.uploadFile({ path: item.tempFilePath, name, size: item.size })
        }
      })
    },

    previewImage(e) {
      const url = e.currentTarget.dataset.url
      if (!url) return
      wx.previewImage({ urls: [url], current: url })
    },

    uploadFile(file) {
      wx.showLoading({ title: '上传中...' })
      const token = app.globalData.token
      const that = this

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
            const fullUrl = data.url.startsWith('http')
              ? data.url
              : app.globalData.serverUrl + data.url
            const isImage = that._isImageFile(file.name)
            const fileMsg = {
              id: Date.now(),
              role: 'user',
              file: {
                id: data.id,
                name: file.name,
                url: fullUrl,
                isImage
              }
            }
            const messages = [...that.data.messages, fileMsg]
            that.setData({ messages, scrollToView: 'msg-bottom' })
            if (isImage && data.id) {
              that.analyzeImage(data.id).catch((err) => {
                wx.showToast({ title: err.message || '图片识别失败', icon: 'none' })
              })
            }
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
          content: '你好！我是内账助手，可以帮助你记录和管理财务收支。\n\n你可以这样跟我说话：\n- "今天午餐花了50元"\n- "查询本周的支出"\n- "本月团队收支汇总"\n\n说明：出现黄色「请确认是否保存」卡片时，需点击「确认保存」才会真正入账；仅对话里口头说已记账而未出现确认卡片或「已记录支出」提示，表示尚未写入账目。'
        }]
      })
    }
  }
})
