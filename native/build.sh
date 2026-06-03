#!/bin/bash
# генерит soul.xcodeproj из project.yml и открывает в Xcode.
# требования: полный Xcode (App Store) + xcodegen (brew install xcodegen).
set -e
cd "$(dirname "$0")"

if ! command -v xcodegen >/dev/null 2>&1; then
  echo "нет xcodegen → brew install xcodegen"; exit 1
fi

echo "→ генерю проект…"
xcodegen generate

if ! xcode-select -p 2>/dev/null | grep -q "Xcode.app"; then
  echo ""
  echo "⚠️  активны только Command Line Tools, не полный Xcode."
  echo "   поставь Xcode из App Store, затем:"
  echo "   sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
  echo ""
fi

echo "→ открываю soul.xcodeproj"
open soul.xcodeproj
echo ""
echo "в Xcode:"
echo "  1. выбери таргет soul, схему 'My Mac' (Mac) или свой iPhone."
echo "  2. Signing & Capabilities → Team = твой Apple ID (бесплатный сойдёт)."
echo "  3. ⌘R — запуск."
