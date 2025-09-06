import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: false,
})

// FIXME : Interceptors are commented out for now
// Request interceptor (ex: ajouter token)
// api.interceptors.request.use(
//   (config) => {
//     const token = localStorage.getItem('auth_token')
//     if (token && config.headers) {
//       config.headers.Authorization = `Bearer ${token}`
//     }
//     return config
//   },
//   (error) => Promise.reject(error)
// )

// api.interceptors.response.use(
//   (response) => response.data,
//   (error) => {
//     // gestion centralisée d'erreur (log, toast, format)
//     const err = error?.response?.data || { message: error.message || 'Erreur réseau' }
//     return Promise.reject(err)
//   },
// )

export default api
