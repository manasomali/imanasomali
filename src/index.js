import React from 'react';
import ReactDOM from 'react-dom';
import './index.css';
import Main from './pages/Main'
import Sobre from './pages/Sobre';
import Publicacoes from './pages/Publicacoes';
import Pagina404 from "./pages/Pagina404";
import Projetos from "./pages/Projetos";

import {BrowserRouter, Switch, Route } from 'react-router-dom'

ReactDOM.render(
  <BrowserRouter>
    <Switch>
      <Route path="/" component={Main} exact/>
      <Route path="/sobre" component={Sobre} />
      <Route path="/projetos" component={Projetos} />
      <Route path="/publicacoes" component={Publicacoes} />
      <Route component={Pagina404} />
    </Switch>
  </BrowserRouter>,
  document.getElementById('root')
);