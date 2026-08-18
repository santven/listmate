
// Dynamic SSO Button Ordering, Highlighting, and Privacy Notice
document.addEventListener("DOMContentLoaded", function() {
  var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var isMac = /Mac/.test(navigator.platform);
  var isApplePlatform = isIOS || isMac;
  
  var authContainer = document.getElementById('authButtonsContainer');
  var btnGoogle = document.getElementById('btnGoogle');
  var btnApple = document.getElementById('btnApple');
  
  if (authContainer && btnGoogle && btnApple) {
    if (isApplePlatform) {
      // Apple is preferred on Apple devices
      btnApple.style.background = '#000';
      btnApple.style.color = '#fff';
      btnApple.style.border = 'none';
      btnApple.style.boxShadow = '0 0 0 2px rgba(0,0,0,0.2)'; // Visual solid highlight
      
      btnGoogle.style.background = '#fff';
      btnGoogle.style.color = '#3c4043';
      btnGoogle.style.border = '1px solid #dadce0';
      btnGoogle.style.boxShadow = 'none';
      
      authContainer.appendChild(btnApple);
      authContainer.appendChild(btnGoogle);
    } else {
      // Google is preferred
      btnGoogle.style.background = '#e8f0fe'; // Slight blue solid background
      btnGoogle.style.color = '#1967d2'; // Darker blue text for contrast
      btnGoogle.style.border = '1px solid #4285F4'; // Solid border highlight
      btnGoogle.style.boxShadow = '0 0 0 2px rgba(66, 133, 244, 0.2)';
      
      btnApple.style.background = '#fff';
      btnApple.style.color = '#3c4043';
      btnApple.style.border = '1px solid #dadce0';
      btnApple.style.boxShadow = 'none';
      
      var appleSvgPath = btnApple.querySelector('svg path');
      if (appleSvgPath) {
         var appleSvg = btnApple.querySelector('svg');
         appleSvg.style.fill = '#000';
      }
      
      authContainer.appendChild(btnGoogle);
      authContainer.appendChild(btnApple);
    }

    // High-trust one-way SSO privacy guarantee
    var privacyNote = document.createElement('div');
    privacyNote.style.fontSize = '12px';
    privacyNote.style.color = '#4a5d4e';
    privacyNote.style.background = '#f4f8f3';
    privacyNote.style.border = '1px solid #dce8d9';
    privacyNote.style.borderRadius = '10px';
    privacyNote.style.padding = '8px 12px';
    privacyNote.style.marginTop = '6px';
    privacyNote.style.lineHeight = '1.4';
    privacyNote.style.textAlign = 'center';
    privacyNote.style.maxWidth = '300px';
    privacyNote.innerHTML = '🔒 <strong>One-way sign in:</strong> We only receive your name &amp; email to log you in. Your grocery lists and household data are <strong>never</strong> shared with Google or Apple.';
    
    authContainer.appendChild(privacyNote);
  }
});
