<script setup lang="ts">
import { RouterView, RouterLink } from 'vue-router'
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
} from '@/components/ui/navigation-menu'
</script>

<template>
  <div class="min-h-screen">
    <NavigationMenu class="max-w-none w-full p-2">
      <NavigationMenuList>
        <NavigationMenuItem>
          <NavigationMenuLink as-child>
            <RouterLink to="/">Home</RouterLink>
          </NavigationMenuLink>
        </NavigationMenuItem>
        <NavigationMenuItem>
          <NavigationMenuLink as-child>
            <RouterLink to="/datasets">Datasets</RouterLink>
          </NavigationMenuLink>
        </NavigationMenuItem>
      </NavigationMenuList>
    </NavigationMenu>
    <main>
      <RouterView />
    </main>
  </div>
</template>
