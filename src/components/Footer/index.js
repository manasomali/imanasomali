import React from 'react'
import Link from '../Link'
import './Footer.css'

function Footer() {
    return (
        <nav className="Footer" >
            <div>Developed by Matheus Nascimento</div>
            <div>Using <Link href="https://pt-br.reactjs.org" target="_blank">React</Link></div>
            <div>2020</div>
        </nav>
    )
}
export default Footer