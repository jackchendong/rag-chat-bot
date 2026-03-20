<script setup lang="ts">
import { computed, type HTMLAttributes } from 'vue'

import { cn } from '../../lib/utils'
import { buttonVariants, type ButtonVariants } from './button'

interface Props {
  class?: HTMLAttributes['class']
  variant?: ButtonVariants['variant']
  size?: ButtonVariants['size']
  type?: 'button' | 'submit' | 'reset'
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'default',
  size: 'default',
  type: 'button',
})

const className = computed(() => cn(buttonVariants({ variant: props.variant, size: props.size }), props.class))
</script>

<template>
  <button :type="props.type" :class="className">
    <slot />
  </button>
</template>
