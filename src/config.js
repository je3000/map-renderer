// Set this to the deployed backend URL when the frontend is hosted separately.
// Leave empty for local development.
window.TOPO_API_URL = ["localhost", "127.0.0.1"].includes(window.location.hostname)
  ? ""
  : "https://map-renderer.onrender.com";
