# Use Node 18 Alpine as base image
FROM node:18-alpine

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --legacy-peer-deps

# Copy source code
COPY . .

# Expose port 3000
EXPOSE 3000

# Set environment
ENV NODE_ENV=development

# Start in development mode (simpler, works reliably)
CMD ["npm", "run", "dev"]
