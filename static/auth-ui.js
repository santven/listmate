
// Dynamic SSO Button Ordering and Highlighting
document.addEventListener("DOMContentLoaded", function() {
  var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var isMac = /Mac/.test(navigator.platform);
  var isApplePlatform = isIOS || isMac;
  
  var authContainer = document.getElementById('authButtonsContainer');
  var btnGoogle = document.getElementById('btnGoogle');
  var btnApple = document.getElementById('btnApple');
  
  if (authContainer && btnGoogle && btnApple) {
    // Create the message container
    var platformNote = document.createElement('div');
    platformNote.style.fontSize = '12px';
    platformNote.style.color = '#666';
    platformNote.style.marginTop = '8px';
    platformNote.style.textAlign = 'center';
    
    if (isApplePlatform) {
      // Apple is preferred
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
      
      platformNote.innerText = "Note: Google sign-in provides a browser-based experience.";
      authContainer.appendChild(platformNote);
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
      // Change apple icon to black since background is white
      var appleSvgPath = btnApple.querySelector('svg path');
      if (appleSvgPath) {
         // The original has fill="#fff" on the svg or the paths, let's reset it
         var appleSvg = btnApple.querySelector('svg');
         appleSvg.style.fill = '#000';
      }
      
      authContainer.appendChild(btnGoogle);
      authContainer.appendChild(btnApple);
      
      platformNote.innerText = "Note: Apple sign-in provides a browser-based experience.";
      authContainer.appendChild(platformNote);
    }
  }
});
