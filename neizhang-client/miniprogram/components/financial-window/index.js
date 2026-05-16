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
    teamSummary: null,
    personalSummary: null,
    transactions: [],
    loading: false
  },

  observers: {
    refreshNonce(n) {
      if (n > 0) {
        this.loadData()
      }
    }
  },

  lifetimes: {
    attached() {
      this._financeRefreshHandler = () => this.loadData()
      app.onFinanceRefresh(this._financeRefreshHandler)
      this.loadData()
    },
    detached() {
      if (this._financeRefreshHandler) {
        app.offFinanceRefresh(this._financeRefreshHandler)
      }
    }
  },

  pageLifetimes: {
    show() {
      if (app.globalData.financeStale) {
        app.globalData.financeStale = false
      }
      this.loadData()
    }
  },

  methods: {
    setFilter(e) {
      const filter = e.currentTarget.dataset.filter
      this.setData({ currentFilter: filter })
      this.loadData()
    },

    getDateRange() {
      const now = new Date()
      const format = (d) => {
        const y = d.getFullYear()
        const m = String(d.getMonth() + 1).padStart(2, '0')
        const day = String(d.getDate()).padStart(2, '0')
        return `${y}-${m}-${day}`
      }

      const endDate = format(now)
      let startDate

      switch (this.data.currentFilter) {
        case 'today':
          startDate = endDate
          break
        case 'week': {
          const day = now.getDay()
          const diff = day === 0 ? 6 : day - 1
          const monday = new Date(now)
          monday.setDate(now.getDate() - diff)
          startDate = format(monday)
          break
        }
        case 'month':
          startDate = format(new Date(now.getFullYear(), now.getMonth(), 1))
          break
        case 'year':
          startDate = format(new Date(now.getFullYear(), 0, 1))
          break
        default:
          startDate = '2020-01-01'
      }

      return { start_date: startDate, end_date: endDate }
    },

    async loadData() {
      if (!app.globalData.token) return

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
