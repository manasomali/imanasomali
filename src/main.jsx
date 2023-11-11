import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import Main from './pages/Main'
import About from './pages/About';
import Publications from './pages/Publications';
import Page404 from "./pages/Page404";
import Projects from "./pages/Projects";
import {BrowserRouter, Switch, Route } from 'react-router-dom'
import './i18n';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
    <Switch>
      <Route path="/" component={Main} exact/>
      <Route path="/about" component={About} />
      <Route path="/projects" component={Projects} />
      <Route path="/publications" component={Publications} />
      <Route component={Page404} />
    </Switch>
  </BrowserRouter>
  </React.StrictMode>
)
