
document.addEventListener("DOMContentLoaded", function () {
    const themeToggle = document.querySelector(".theme-toggle");
    const body = document.body;
    const icon = themeToggle.querySelector("i");
    const savedTheme = localStorage.getItem("theme") || "light";
    body.setAttribute("data-theme", savedTheme);
    icon.className = savedTheme === "dark" ? "fas fa-sun" : "fas fa-moon";

    themeToggle.addEventListener("click", () => {
        const currentTheme = body.getAttribute("data-theme");
        const newTheme = currentTheme === "light" ? "dark" : "light";
        body.setAttribute("data-theme", newTheme);
        icon.className = newTheme === "dark" ? "fas fa-sun" : "fas fa-moon";
        localStorage.setItem("theme", newTheme);
    });

    const tabButtons = document.querySelectorAll(".tab-button");
    const tabContents = document.querySelectorAll(".tab-content");

    tabButtons.forEach(button => {
        button.addEventListener("click", () => {
            tabButtons.forEach(btn => btn.classList.remove("active"));
            tabContents.forEach(content => content.classList.remove("active"));

            button.classList.add("active");
            const tabId = button.getAttribute("data-tab");
            document.getElementById(tabId).classList.add("active");
        });
    });

    const roomId = "{{ room.id }}";
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const summaryContent = document.getElementById('summary-content');
    const summarizingMessage = document.getElementById('summarizing-message');
    const quizContent = document.getElementById('quiz-content');

    const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
    const wsUrl = `${protocol}${window.location.host}/ws/room/${roomId}/`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = function () {
        console.log('WebSocket connection established');
    };

    ws.onmessage = function (event) {
        const data = JSON.parse(event.data);
        console.log('Received WebSocket message:', data);

        if (data.type === 'chat_message') {
            const messageDiv = document.createElement('div');
            messageDiv.classList.add('chat-message');
            if (data.is_ai_response) {
                messageDiv.classList.add('ai-message');
            } else if (data.username === "{{ user.name }}") {
                messageDiv.classList.add('mine');
            } else {
                messageDiv.classList.add('other');
            }

            let messageContent = data.message;
            if (data.mentions && data.mentions.length > 0) {
                data.mentions.forEach(mention => {
                    const regex = new RegExp(`@${mention}\\b`, 'g');
                    messageContent = messageContent.replace(regex, `<span class="mention">@${mention}</span>`);
                });
            }

            messageDiv.innerHTML = `
                <span class="username">${data.username}</span>
            <span class="timestamp">${new Date(data.timestamp).toLocaleTimeString()}</span>
                <div class="message-content">${messageContent}</div>
            `;
            chatMessages.appendChild(messageDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        } else if (data.type === 'summarizing_start') {
            summarizingMessage.style.display = 'block';
            summaryContent.style.display = 'none';
            chatInput.disabled = true;
            sendButton.disabled = true;
        } else if (data.type === 'final_summary') {
        isSummarizing = false;
            summarizingMessage.style.display = 'none';
            summaryContent.style.display = 'block';

        // Append the new summary
            const summaryItem = document.createElement('div');
            summaryItem.classList.add('summary-item');
            summaryItem.innerHTML = `
                <span class="pdf-name">${data.pdf_name}</span>
                <p><strong>${data.username}:</strong> ${data.summary}</p>
            `;
            summaryContent.insertBefore(summaryItem, summaryContent.firstChild);

        // Remove "No summaries available" message if it exists
            const noSummariesMessage = summaryContent.querySelector('p');
            if (noSummariesMessage && noSummariesMessage.textContent.includes('No summaries available')) {
                noSummariesMessage.remove();
            }

        // Enable chat for all users
            chatInput.disabled = false;
            sendButton.disabled = false;
    } else if (data.type === 'chat_message') {
        const messageDiv = document.createElement('div');
        const isMine = data.username === "{{ user.name }}";
        const isAI = data.is_ai_response;
        messageDiv.classList.add('chat-message', isAI ? 'ai-message' : (isMine ? 'mine' : 'other'));

        let messageContent = data.message;
        if (data.mentions && data.mentions.length > 0) {
            data.mentions.forEach(mention => {
                messageContent = messageContent.replace(
                    new RegExp(`@${mention}\\b`, 'g'),
                    `<span class="mention">@${mention}</span>`
                );
            });
        }

        messageDiv.innerHTML = `
            <span class="username">${data.username}</span>
            <span class="timestamp">${new Date(data.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            <div class="message-content">${messageContent}</div>
        `;
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }else if (data.type === 'quiz') {
    quizContent.innerHTML = '';
    data.quizzes.forEach(quiz => {
        const quizItem = document.createElement('div');
        quizItem.classList.add('quiz-item');
        quizItem.innerHTML = `
                                <p>${quiz.question}</p>
                                <ul>
                                    ${Object.entries(quiz.options).map(([key, value]) => `
                                        <li>
                                            <label>
                            <input type="radio" name="quiz_${quiz.id}" value="${key}"
                                onchange="submitQuizResponse(${quiz.id}, this.value)">
                                                ${key}: ${value}
                                            </label>
                                        </li>
                                    `).join('')}
                                </ul>
        `;
        quizContent.appendChild(quizItem);
    });
        } else if (data.type === 'ranking') {
            quizContent.innerHTML = `
                <div class="quiz-ranking">
                    <h4>Quiz Ranking</h4>
                    <ol>
                ${data.rankings.map(([name, score]) => `<li>${name}: ${score}/5</li>`).join('')}
                    </ol>
                </div>
            `;
        } else if (data.type === 'error') {
            console.error('WebSocket error:', data.message);
            alert(`Error: ${data.message}`);
        }
    };


    ws.onclose = function () {
        console.log('WebSocket connection closed');
    };

    ws.onerror = function (error) {
        console.error('WebSocket error:', error);
    };

    window.sendMessage = function () {
        const message = chatInput.value.trim();
    if (message) {
    ws.send(JSON.stringify({
                'type': 'chat_message',
                'message': message,
                'username': "{{ user.name }}"
    }));
            chatInput.value = '';
}
    };

window.submitQuizResponse = function (quizId, selectedAnswer) {
ws.send(JSON.stringify({
                    'type': 'quiz_response',
    'quiz_id': quizId,
    'selected_answer': selectedAnswer,
                    'username': "{{ user.name }}"
}));
    };
window.submitQuizForm = function () {
const form = document.getElementById('quiz-form');
const quizzes = JSON.parse(document.getElementById("quizzes").textContent);

quizzes.forEach(quiz => {
const selectedAnswer = form.querySelector(`input[name="quiz_${quiz.id}"]:checked`);
if (selectedAnswer) {
ws.send(JSON.stringify({
    'type': 'quiz_response',
    'quiz_id': quiz.id,
    'selected_answer': selectedAnswer.value,
    'username': "{{ user.name }}"
}));
}
});
alert("Quiz submitted successfully!");
};
    chatInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });
});
const roomStartTime = new Date("{{ room.date }}T{{ room.time }}").getTime();
const currentTime = Date.now();
const timeElapsed = currentTime - roomStartTime;
const timeToQuiz = (20 * 60 * 1000) - timeElapsed;

if (timeToQuiz > 0) {
setTimeout(() => {
    if (isQuizSession) {
        ws.send(JSON.stringify({
            'type': 'quiz',
            'quizzes': quizzes
        }));
    }
}, timeToQuiz);
}

