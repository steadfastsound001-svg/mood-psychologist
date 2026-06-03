#!/bin/bash
# Архив + экспорт IPA для App Store.
# Требования: полный Xcode, членство в Apple Developer Program ($99/год),
# сертификаты в Keychain (Xcode → Settings → Accounts → твой Apple ID → Manage Certificates),
# Team ID подставлен в TEAM ниже и в ExportOptions.plist.
set -e
cd "$(dirname "$0")"

TEAM="${APPLE_TEAM_ID:-ЗАМЕНИ_НА_TEAM_ID}"
if [ "$TEAM" = "ЗАМЕНИ_НА_TEAM_ID" ]; then
  echo "⚠️  задай Team ID: APPLE_TEAM_ID=XXXXXXXXXX ./archive.sh"
  echo "   (Apple Developer → Membership → Team ID)"
  exit 1
fi

xcodegen generate

echo "→ архивирую (iOS, Release)…"
xcodebuild -project soul.xcodeproj -scheme soul -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath build/soul.xcarchive \
  DEVELOPMENT_TEAM="$TEAM" CODE_SIGN_STYLE=Automatic \
  clean archive

echo "→ экспортирую IPA…"
sed "s/ЗАМЕНИ_НА_TEAM_ID/$TEAM/" ExportOptions.plist > build/ExportOptions.plist
xcodebuild -exportArchive \
  -archivePath build/soul.xcarchive \
  -exportOptionsPlist build/ExportOptions.plist \
  -exportPath build/ipa

echo ""
echo "✅ IPA: native/build/ipa/soul.ipa"
echo "загрузить в App Store Connect:"
echo "  xcrun altool --upload-app -f build/ipa/soul.ipa -t ios \\"
echo "    --apiKey \$ASC_KEY_ID --apiIssuer \$ASC_ISSUER_ID"
echo "  (или открой build/soul.xcarchive в Xcode → Organizer → Distribute App)"
