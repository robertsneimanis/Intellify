// PM2 process file for the ingest service.
//
//   pm2 start ecosystem.config.js     # start (reads settings from .env)
//   pm2 save && pm2 startup           # start on boot; run the command `pm2 startup` prints
//   pm2 logs ingest                   # follow logs
//
// PM2 stops the process with SIGINT, which the service handles as a clean shutdown.

const fs = require("fs");
const path = require("path");

function loadEnv(file) {
  if (!fs.existsSync(file)) return {};
  const env = {};
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (match) env[match[1]] = match[2].replace(/^(['"])(.*)\1$/, "$2");
  }
  return env;
}

module.exports = {
  apps: [
    {
      name: "ingest",
      cwd: __dirname,
      script: path.join(__dirname, ".venv/bin/python"),
      args: "-m ingest",
      interpreter: "none",
      env: loadEnv(path.join(__dirname, ".env")),
      autorestart: true,
      restart_delay: 5000,
      kill_timeout: 15000,
    },
  ],
};
