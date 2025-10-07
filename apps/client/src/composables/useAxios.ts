// import axios from 'axios'

// const api = axios.create({
//   baseURL: import.meta.env.VITE_API_BASE_URL || '',
//   headers: {
//     'Content-Type': 'application/json',
//   },
//   withCredentials: false,
// })

import { client } from '@/api/client.gen'

const api = client.setConfig({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  headers: {
    'Content-Type': 'application/json',
  },
})

export default api
