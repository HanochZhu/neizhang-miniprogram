const app = getApp()
const api = require('../../services/api')

Component({
  data: {
    currentFilter: 'month',
    teamSummary: null,
    personalSummary: null,
    transactions: []
  },

  lifetimes: {
    attached() {
      this.loadData()
    }
  },

  pageLifetimes: {
    show() {
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

      let startDate, endDate
      endDate = format(now)

      switch (this.data.currentFilter) {
        case 'today':
          startDate = endDate
          break
        case 'week':
          const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
          startDate = format(weekAgo)
          break
        case 'month':
          const monthAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)
          startDate = format(monthAgo)
          break
        case 'year':
          const yearAgo = new Date(now.getFullYear() - 1, now.getMonth(), now.getDate())
          startDate = format(yearAgo)
          break
        default:
          startDate = '2020-01-01'
      }

      return { start_date: startDate, end_date: endDate }
    },

    async loadData() {
      if (!app.checkLogin()) return

      const dateRange = this.getDateRange()

      try {
        const [teamRes, personalRes] = await Promise.all([
          api.get('/api/v1/finance/summary', { scope: 'team', ...dateRange }),
          api.get('/api/v1/finance/summary', { scope: 'personal', ...dateRange })
        ])

        this.setData({
          teamSummary: teamRes,
          personalSummary: personalRes,
          transactions: (teamRes.transactions || []).slice(0, 20)
        })
      } catch (err) {
        console.error('Failed to load finance data:', err)
      }
    }
  }
})
