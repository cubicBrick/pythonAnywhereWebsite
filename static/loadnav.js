document.addEventListener("DOMContentLoaded", function() {
    // Create the header element first
    let header = document.createElement("header");
    header.innerHTML = `
        <h1>Welcome to my website</h1>
    `;

    // Create the nav element
    let nav = document.createElement("nav");
    nav.innerHTML = `
        <a href="#">Home</a>
        <a href="/calculator">Calculator</a>
        <a href="/all">All stuff</a>
        ${isAuthenticated ? '<a href="/logout">Logout</a>' : '<a href="/login">Login</a>'}
    `;

    // Get the placeholder div
    let navPlaceholder = document.getElementById("nav-placeholder");

    // First, append the header
    navPlaceholder.appendChild(header);

    // Then, append the nav (ensuring it's placed below the header)
    navPlaceholder.appendChild(nav);
});
