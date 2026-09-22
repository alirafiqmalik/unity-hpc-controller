/**
 * The entry point. `index.html` loads this one module.
 *
 * Provider order matters: the theme wraps everything so `styled` always has a
 * theme; Recoil wraps the sync cycle that writes into it; the toast provider
 * sits above the panels, because a panel reports through it.
 */

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { RecoilRoot } from 'recoil';

import { App } from './App';
import { ControllerSyncProvider } from './modules/controller/ControllerSync';
import { PanelProvider } from './modules/panels/PanelProvider';
import { ToastProvider } from './ui/components/Toast';
import { AppThemeProvider } from './ui/theme/AppThemeProvider';

const container = document.getElementById('root');

if (!container) {
  throw new Error('index.html must hold <div id="root">');
}

createRoot(container).render(
  <StrictMode>
    <AppThemeProvider>
      <ToastProvider>
        <RecoilRoot>
          <ControllerSyncProvider>
            <BrowserRouter>
              <PanelProvider>
                <App />
              </PanelProvider>
            </BrowserRouter>
          </ControllerSyncProvider>
        </RecoilRoot>
      </ToastProvider>
    </AppThemeProvider>
  </StrictMode>,
);
