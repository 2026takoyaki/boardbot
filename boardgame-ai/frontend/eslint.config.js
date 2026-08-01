import reactHooks from 'eslint-plugin-react-hooks'

/**
 * 최소 설정. 스타일은 보지 않고 "실행하면 터지는 것"만 잡는다.
 *
 * vite 빌드는 정의되지 않은 변수를 잡지 못한다. 번들은 멀쩡히 만들어지고
 * 화면을 열어야 ReferenceError로 죽는다 — 백엔드 상수 이름을 그대로 JSX에
 * 써넣어 화면이 검게 나온 적이 있다. no-undef 하나가 그걸 막는다.
 *
 * exhaustive-deps도 같은 이유로 켠다. 매 렌더마다 새로 만들어지는 콜백을
 * useEffect 의존성에 넣어 타이머가 계속 리셋되던 버그를 이 규칙이 잡는다.
 *
 *     npm run lint
 */
export default [
  {
    files: ['src/**/*.{js,jsx}'],
    plugins: { 'react-hooks': reactHooks },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: {
        window: 'readonly',
        document: 'readonly',
        location: 'readonly',
        navigator: 'readonly',
        localStorage: 'readonly',
        sessionStorage: 'readonly',
        fetch: 'readonly',
        console: 'readonly',
        performance: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        requestAnimationFrame: 'readonly',
        cancelAnimationFrame: 'readonly',
        WebSocket: 'readonly',
        Audio: 'readonly',
        Image: 'readonly',
        URLSearchParams: 'readonly',
        ResizeObserver: 'readonly',
        AbortController: 'readonly',
        MutationObserver: 'readonly',
        getComputedStyle: 'readonly',
        alert: 'readonly',
        AudioContext: 'readonly',
        URL: 'readonly',
        URLSearchParams: 'readonly',
        webkitAudioContext: 'readonly',
        screen: 'readonly',
        history: 'readonly',
        CustomEvent: 'readonly',
        Event: 'readonly',
        Blob: 'readonly',
        FileReader: 'readonly',
        structuredClone: 'readonly',
      },
    },
    rules: {
      'no-undef': 'error',
      // 안 쓰는 변수는 대개 지우다 만 흔적이다. 대문자 컴포넌트는 JSX에서
      // 쓰이지만 파서가 모르므로 제외한다.
      'no-unused-vars': [
        'warn',
        { varsIgnorePattern: '^[A-Z_]', argsIgnorePattern: '^_', caughtErrors: 'none' },
      ],
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
]
