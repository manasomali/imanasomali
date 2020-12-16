import React from 'react';
import ReactDOM from 'react-dom';
import './index.css';
import Main from './pages/Main'
import Sobre from './pages/Sobre';
import Pagina404 from "./pages/Pagina404";

import {BrowserRouter, Switch, Route } from 'react-router-dom'

ReactDOM.render(
  <BrowserRouter>
    <Switch>
      <Route path="/" component={Main} exact/>
      <Route path="/sobre" component={Sobre} />
      <Route component={Pagina404} />
    </Switch>
  </BrowserRouter>,
  document.getElementById('root')
);