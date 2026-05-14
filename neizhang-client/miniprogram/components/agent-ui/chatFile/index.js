// Simplified chatFile component for Neizhang
// Displays files with { name, url } properties
Component({
  properties: {
    file: {
      type: Object,
      value: { name: '', url: '' }
    },
    enableDel: {
      type: Boolean,
      value: false
    }
  },

  data: {
    iconPath: '../imgs/file.svg',
    formatSize: ''
  },

  lifetimes: {
    attached() {
      const fileName = this.data.file.name || ''
      const type = this.getFileType(fileName)
      this.setData({
        iconPath: '../imgs/' + type + '.svg'
      })
    }
  },

  methods: {
    getFileType(fileName) {
      let index = fileName.lastIndexOf('.')
      if (index === -1) return 'file'
      const fileExt = fileName.substring(index + 1).toLowerCase()
      if (['docx', 'doc'].includes(fileExt)) return 'word'
      if (['xlsx', 'xls', 'csv'].includes(fileExt)) return 'excel'
      if (['png', 'jpg', 'jpeg', 'svg', 'gif', 'webp'].includes(fileExt)) return 'image'
      if (['ppt', 'pptx'].includes(fileExt)) return 'ppt'
      if (fileExt === 'pdf') return 'pdf'
      return 'file'
    },

    openFile() {
      const { url, name } = this.data.file
      if (!url) return

      const ext = name.split('.').pop().toLowerCase()
      if (['png', 'jpg', 'jpeg', 'svg', 'gif', 'webp'].includes(ext)) {
        wx.previewImage({
          urls: [url],
          showmenu: true
        })
      } else if (['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'pdf'].includes(ext)) {
        wx.downloadFile({
          url: url,
          success(res) {
            wx.openDocument({
              filePath: res.tempFilePath,
              success() {
                console.log('打开文档成功')
              },
              fail(err) {
                console.log('打开文档失败', err)
              }
            })
          },
          fail(err) {
            console.log('下载文件失败', err)
          }
        })
      } else {
        // Fallback: try to open the URL directly
        wx.setClipboardData({
          data: url,
          success() {
            wx.showToast({ title: '文件链接已复制', icon: 'none' })
          }
        })
      }
    }
  }
})
