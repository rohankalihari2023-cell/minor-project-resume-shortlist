document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("form").forEach(form => {
        form.addEventListener("submit", () => {
            const btn = form.querySelector("button");
            if (btn) {
                btn.innerText = "Please wait...";
                btn.disabled = true;
            }
        });
    });
});
