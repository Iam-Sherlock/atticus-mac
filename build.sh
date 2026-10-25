#!/bin/bash
# Installs Jarvis: builds Jarvis.app, starts it at login, and (re)starts it now. Run it again after any change.
set -e; cd "$(dirname "$0")"
VERSION=$(tr -d '\n' < VERSION)
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid VERSION: $VERSION"; exit 1; }
IFS=. read -r VERSION_MAJOR VERSION_MINOR VERSION_PATCH <<< "$VERSION"
(( VERSION_MINOR < 1000 && VERSION_PATCH < 1000 )) || { echo "VERSION components must be below 1000"; exit 1; }
BUILD=$((VERSION_MAJOR * 1000000 + VERSION_MINOR * 1000 + VERSION_PATCH))
[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 26 ] || { echo "Jarvis needs macOS 26 or later (it uses Apple's new on-device speech)."; exit 1; }
xcode-select -p >/dev/null 2>&1 || { echo "Needs Apple's command line tools. Run: xcode-select --install   then run ./build.sh again."; exit 1; }
command -v python3 >/dev/null || { echo "Jarvis needs Python 3. Install it, then run ./build.sh again."; exit 1; }
command -v claude >/dev/null || [ -x ~/.local/bin/claude ] || echo "Note: Claude Code is not installed yet. Jarvis's setup window can install it, or you can pick Devin or Pi."
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
# A compiler error must leave the installed app and its resources alone.
swiftc -O -target "$(uname -m)-apple-macos26.0" Jarvis.swift -o "$STAGE/Jarvis"
APP=~/Applications/Jarvis.app   # in Applications so System Settings can list it for permissions
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/ui"
cp jarvis.py "$APP/Contents/Resources/"
cp ui/*.html ui/*.js "$APP/Contents/Resources/ui/"
cp ui/AppIcon.icns "$APP/Contents/Resources/"
cat > "$APP/Contents/Info.plist" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.jarvis.app</string>
<key>CFBundleName</key><string>Jarvis</string>
<key>CFBundleExecutable</key><string>Jarvis</string>
<key>CFBundleVersion</key><string>$BUILD</string>
<key>CFBundleShortVersionString</key><string>$VERSION</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>JarvisSource</key><string>$(pwd)</string>
<key>LSUIElement</key><true/>
<key>NSMicrophoneUsageDescription</key><string>Jarvis listens when you use its shortcut or microphone button.</string>
<key>NSAppleEventsUsageDescription</key><string>Jarvis controls apps like Finder, Chrome and Music when you ask it to.</string>
<key>NSCalendarsFullAccessUsageDescription</key><string>Jarvis reads your calendar, adds events you request, and asks before moving or deleting existing events. Calendar details are sent to your chosen AI model.</string>
<key>NSSpeechRecognitionUsageDescription</key><string>Jarvis turns your words into text on this Mac.</string>
</dict></plist>
P
mv "$STAGE/Jarvis" "$APP/Contents/MacOS/Jarvis"
# With a code-signing identity named "Jarvis Local Signing" in the keychain, macOS keeps permissions across
# rebuilds and auto-updates; ad hoc signing would ask for every permission again after each one. So make it once.
ID=$(security find-identity -p codesigning | awk '/Jarvis Local Signing/{print $2; exit}')
if [ -z "$ID" ]; then
  K=$(mktemp -d)
  /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 7300 -subj "/CN=Jarvis Local Signing" -addext "extendedKeyUsage=critical,codeSigning" \
    -addext "keyUsage=critical,digitalSignature" -keyout "$K/k.pem" -out "$K/c.pem" 2>/dev/null &&
  /usr/bin/openssl pkcs12 -export -inkey "$K/k.pem" -in "$K/c.pem" -out "$K/a.p12" -passout pass:jarvis 2>/dev/null &&
  security import "$K/a.p12" -P jarvis -T /usr/bin/codesign >/dev/null 2>&1 || true   # fails quietly: ad hoc still works
  rm -rf "$K"
  ID=$(security find-identity -p codesigning | awk '/Jarvis Local Signing/{print $2; exit}')
fi
codesign -s "${ID:--}" --force "$APP"
# register with macOS, or System Settings can't list it for permissions
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"
# Coming from Atticus: keep its settings, memory and history, and stop the old app so two copies never fight over one shortcut.
if [ -d ~/.config/atticus ] && [ ! -L ~/.config/atticus ] && [ ! -e ~/.config/jarvis ]; then
  mv ~/.config/atticus ~/.config/jarvis && ln -s ~/.config/jarvis ~/.config/atticus   # the link keeps paths saved inside old files working
  echo "Moved your Atticus settings, memory and history to ~/.config/jarvis."
fi
for OLD in ~/Library/LaunchAgents/com.atticus.app.plist ~/Library/LaunchAgents/com.atticus.routine.*.plist; do
  [ -f "$OLD" ] || continue   # routines come back under com.jarvis.routine the next time Jarvis starts
  launchctl bootout gui/$(id -u) "$OLD" 2>/dev/null || true
  rm -f "$OLD"
done
pkill -f "/Atticus.app/Contents/MacOS/Atticus$" 2>/dev/null || true
AGENT=~/Library/LaunchAgents/com.jarvis.app.plist   # starts at login, restarts if it crashes (Quit stays quit)
mkdir -p ~/Library/LaunchAgents ~/.config/jarvis
cat > "$AGENT" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.jarvis.app</string>
<key>ProgramArguments</key><array><string>$APP/Contents/MacOS/Jarvis</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
<key>StandardErrorPath</key><string>$HOME/.config/jarvis/app.err</string>
</dict></plist>
P
[ -n "$JARVIS_NO_RESTART" ] && exit 0   # the app's own updater restarts it when idle
# Reload the job so launchd refreshes its executable signing requirement after a rebuild.
launchctl bootout gui/$(id -u)/com.jarvis.app 2>/dev/null || true
pkill -f "$APP/Contents/MacOS/Jarvis$" 2>/dev/null && sleep 1   # stop a copy opened by hand too
# bootout can return before the job has finished unloading.
launchctl bootstrap gui/$(id -u) "$AGENT" 2>/dev/null || { sleep 1; launchctl bootstrap gui/$(id -u) "$AGENT" 2>/dev/null || {
  echo "Could not add Jarvis to Login Items; opening it directly instead."
  open "$APP"
}; }
echo "Jarvis is running. Hold Control+Option+Space and talk."
