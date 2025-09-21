
const chat = document.getElementById('chat');
const input = document.getElementById('message');
const sendBtn = document.getElementById('send');
const kbEl = document.getElementById('kb');

function addMessage(role, text) {
  const wrap = document.createElement('div');
  wrap.className = `msg ${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  wrap.appendChild(bubble);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
}

async function sendMessage() {
  const text = input.value.trim();
  if (!text) return;
  addMessage('user', text);
  input.value = '';
  sendBtn.disabled = true;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, kb: kbEl.value })
    });
    const data = await res.json();
    if (data.reply) addMessage('bot', data.reply);
    else addMessage('bot', data.error || 'Unknown error');
  } catch (e) {
    addMessage('bot', 'Network error: ' + e.message);
  } finally {
    sendBtn.disabled = false;
  }
}

sendBtn.addEventListener('click', sendMessage);
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendMessage();
});
