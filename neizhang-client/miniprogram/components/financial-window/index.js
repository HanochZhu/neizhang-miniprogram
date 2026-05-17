const app = getApp()
const api = require('../../services/api')

Component({
  properties: {
    refreshNonce: {
      type: Number,
      value: 0
    }
  },

  data: {
    currentFilter: 'month',
    queryEndDate: '',
    teamSummary: null,
    personalSummary: null,
    transactions: [],
    transactionCount: 0,
    transactionsReturned: 0,
    loading: false,
    isAdmin: false,
    editingId: null,
    editForm: {}
  },

  observers: {
    refreshNonce(n) {
      if (n > 0) {
        this.activateAndLoad()
      }
    }
  },

  lifetimes: {
    attached() {
      this._financeRefreshHandler = () => this.reloadData()
      app.onFinanceRefresh(this._financeRefreshHandler)
    },
    detached() {
      if (this._financeRefreshHandler) {
        app.offFinanceRefresh(this._financeRefreshHandler)
      }
    }
  },

  pageLifetimes: {
    show() {
      // 由 main 页在切换到财务 Tab 时调用 activateAndLoad
    }
  },

  methods: {
    _formatDate(d) {
      const y = d.getFullYear()
      const m = String(d.getMonth() + 1).padStart(2, '0')
      const day = String(d.getDate()).padStart(2, '0')
      return `${y}-${m}-${day}`
    },

    _getAnchorDate() {
      if (this.data.queryEndDate) {
        const parts = this.data.queryEndDate.split('-').map(Number)
        return new Date(parts[0], parts[1] - 1, parts[2])
      }
      return new Date()
    },

    /** 打开/切换到财务 Tab：锁定截止日为当前时刻并请求数据 */
    activateAndLoad() {
      const userInfo = app.globalData.userInfo || {}
      this.setData({ isAdmin: userInfo.role === 'admin' })
      const endDate = this._formatDate(new Date())
      this.setData({ queryEndDate: endDate }, () => {
        this.loadData()
      })
    },

    /** 记账成功等刷新：保持原截止日，仅重新请求 */
    reloadData() {
      if (!this.data.queryEndDate) {
        this.activateAndLoad()
        return
      }
      this.loadData()
    },

    setFilter(e) {
      const filter = e.currentTarget.dataset.filter
      this.setData({ currentFilter: filter }, () => {
        this.loadData()
      })
    },

    getDateRange() {
      const format = (d) => this._formatDate(d)
      const anchor = this._getAnchorDate()
      const endDate = this.data.queryEndDate || format(anchor)
      let startDate

      switch (this.data.currentFilter) {
        case 'today':
          startDate = endDate
          break
        case 'week': {
          const day = anchor.getDay()
          const diff = day === 0 ? 6 : day - 1
          const monday = new Date(anchor)
          monday.setDate(anchor.getDate() - diff)
          startDate = format(monday)
          break
        }
        case 'month':
          startDate = format(new Date(anchor.getFullYear(), anchor.getMonth(), 1))
          break
        case 'year':
          startDate = format(new Date(anchor.getFullYear(), 0, 1))
          break
        default:
          startDate = '2020-01-01'
      }

      return { start_date: startDate, end_date: endDate }
    },

    startEdit(e) {
      const { id, type, amount, category, description, product, date } = e.currentTarget.dataset
      this.setData({
        editingId: id,
        editForm: {
          type: type || 'expense',
          typeIdx: type === 'income' ? 0 : 1,
          amount: String(amount || ''),
          category: category || '',
          description: description || '',
          product: product || '',
          transaction_date: date || ''
        }
      })
    },

    cancelEdit() {
      this.setData({ editingId: null, editForm: {} })
    },

    onEditType(e) {
      const idx = parseInt(e.detail.value)
      const types = ['income', 'expense']
      this.setData({ 'editForm.type': types[idx], 'editForm.typeIdx': idx })
    },

    onEditField(e) {
      const field = e.currentTarget.dataset.field
      this.setData({ [`editForm.${field}`]: e.detail.value })
    },

    async saveEdit() {
      const { editingId, editForm } = this.data
      if (!editingId) return

      const type = editForm.type
      const amount = parseFloat(editForm.amount)
      if (isNaN(amount) || amount <= 0) {
        wx.showToast({ title: '请输入有效金额', icon: 'none' })
        return
      }
      if (!editForm.category.trim()) {
        wx.showToast({ title: '请输入类别', icon: 'none' })
        return
      }

      const body = {
        type,
        amount,
        category: editForm.category.trim(),
        description: editForm.description ? editForm.description.trim() : null,
        product: editForm.product ? editForm.product.trim() : null,
        transaction_date: editForm.transaction_date || null
      }

      try {
        await api.put(`/api/v1/finance/transactions/${editingId}`, body)
        wx.showToast({ title: '已更新', icon: 'success' })
        this.setData({ editingId: null, editForm: {} })
        this.loadData()
        app.refreshFinanceData()
      } catch (err) {
        wx.showToast({ title: err.message || '更新失败', icon: 'none' })
      }
    },

    async deleteTransaction(e) {
      const { id, category, amount } = e.currentTarget.dataset
      const confirmed = await new Promise((resolve) => {
        wx.showModal({
          title: '确认删除',
          content: `确定要删除该笔记录吗？\n${category} ¥${amount}`,
          success: (res) => { resolve(res.confirm) }
        })
      })
      if (!confirmed) return

      try {
        await api.del(`/api/v1/finance/transactions/${id}`)
        wx.showToast({ title: '已删除', icon: 'success' })
        this.loadData()
        app.refreshFinanceData()
      } catch (err) {
        wx.showToast({ title: err.message || '删除失败', icon: 'none' })
      }
    },

    async loadData() {
      if (!app.globalData.token) return
      if (!this.data.queryEndDate) {
        this.activateAndLoad()
        return
      }

      const dateRange = this.getDateRange()
      this.setData({ loading: true })

      try {
        const listParams = { ...dateRange, tx_limit: 200 }
        const [teamRes, personalRes] = await Promise.all([
          api.get('/api/v1/finance/summary', { scope: 'team', ...listParams }),
          api.get('/api/v1/finance/summary', { scope: 'personal', ...listParams })
        ])

        const txList = teamRes.transactions || []
        app.globalData.financeStale = false
        this.setData({
          teamSummary: teamRes,
          personalSummary: personalRes,
          transactions: txList,
          transactionCount: teamRes.transaction_count || 0,
          transactionsReturned: teamRes.transactions_returned ?? txList.length,
          loading: false
        })
      } catch (err) {
        console.error('Failed to load finance data:', err)
        this.setData({ loading: false })
      }
    }
  }
})
