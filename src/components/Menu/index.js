import React from 'react'
import Button from '../Button'
import './Menu.css'

function Menu() {
    return (
        <nav className="Menu" >
            <div>
                <Button as="a" className="Button" href="/"> MATHEUS NASCIMENTO </Button>
            </div>
            <div>
                <Button as="a" className="Button" href="/"> SOBRE </Button>
                <Button as="a" className="Button" href="/"> POSTS </Button>
                <Button as="a" className="Button" href="/"> PROJETOS </Button>
            </div>
        </nav>
    )
}
export default Menu