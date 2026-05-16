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
    loading: false
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

    async loadData() {
      if (!app.globalData.token) return
      if (!this.data.queryEndDate) {
        this.activateAndLoad()
        return
      }

      const dateRange = this.getDateRange()
      this.setData({ loading: true })

      try {
        const [teamRes, personalRes] = await Promise.all([
          api.get('/api/v1/finance/summary', { scope: 'team', ...dateRange }),
          api.get('/api/v1/finance/summary', { scope: 'personal', ...dateRange })
        ])

        app.globalData.financeStale = false
        this.setData({
          teamSummary: teamRes,
          personalSummary: personalRes,
          transactions: (teamRes.transactions || []).slice(0, 20),
          loading: false
        })
      } catch (err) {
        console.error('Failed to load finance data:', err)
        this.setData({ loading: false })
      }
    }
  }
})
