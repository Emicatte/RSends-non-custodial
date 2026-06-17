const nextJest = require('next/jest.js')

const createJestConfig = nextJest({ dir: './' })

/** @type {import('jest').Config} */
module.exports = createJestConfig({
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/$1',
    '\\.(css|less|scss|sass)$': 'identity-obj-proxy',
  },
  testMatch: ['<rootDir>/app/__tests__/**/*.{ts,tsx}'],
})
