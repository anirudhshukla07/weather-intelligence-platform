import axios from "axios";
import { API_BASE } from "../config";

export { API_BASE };

const api = axios.create({ baseURL: API_BASE });
export default api;
