#!/bin/sh
set -e

echo "Running ci_post_clone.sh"

# Install Node.js
brew install node

# Navigate to the root of the project
cd ../../../

# Install npm dependencies
npm install

# Sync Capacitor
npx cap sync ios
