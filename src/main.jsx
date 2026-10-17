import { StrictMode, Suspense } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router';
import './index.css';
import './i18n';
import Main from './pages/Main';
import About from './pages/About';
import Projects from './pages/Projects';
import Publications from './pages/Publications';
import Page404 from './pages/Page404';

ReactDOM.createRoot(document.getElementById('root')).render(
  <StrictMode>
    {/* translations load over HTTP, so the first render waits for them */}
    <Suspense fallback={null}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Main />} />
          <Route path="/about" element={<About />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/publications" element={<Publications />} />
          <Route path="*" element={<Page404 />} />
        </Routes>
      </BrowserRouter>
    </Suspense>
  </StrictMode>,
);
