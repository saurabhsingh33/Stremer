package com.stremer.auth

object AuthManager {
    private val users = mapOf("admin" to "password")
    fun validate(username: String, password: String): Boolean = users[username] == password
}
