#!/usr/bin/env python3
"""Inject release signing config into generated android/app/build.gradle."""
import sys, os

build_gradle = sys.argv[1]
st_pass = sys.argv[2]
st_alias = sys.argv[3]

# Create keystore.properties
props = f"""storeFile=../app/listmate-upload.keystore
storePassword={st_pass}
keyAlias={st_alias}
keyPassword={st_pass}
"""
with open(os.path.join(os.path.dirname(build_gradle), '..', 'keystore.properties'), 'w') as f:
    f.write(props)

# Read the existing build.gradle
with open(build_gradle) as f:
    content = f.read()

# Check if signing is already there
if 'signingConfig signingConfigs.release' in content:
    print("Signing already configured")
    sys.exit(0)

# Add signing block before the top-level android { ... buildTypes
signing_block = """
android {
    signingConfigs {
        release {
            def props = new Properties()
            file("../keystore.properties").withInputStream { props.load(it) }
            storeFile file(props["storeFile"])
            storePassword props["storePassword"]
            keyAlias props["keyAlias"]
            keyPassword props["keyPassword"]
        }
    }
    buildTypes {
        release {
            signingConfig signingConfigs.release
        }
    }
}
"""
# Append
with open(build_gradle, 'a') as f:
    f.write(signing_block)

print("Signing config injected")
